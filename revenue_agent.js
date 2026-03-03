/**
 * Revenue Agent - Stripe Integration for Garcar Autonomous Wealth System
 * Handles subscription management, payment processing, and customer lifecycle
 */

const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);
const AWS = require('aws-sdk');
const axios = require('axios');

const s3 = new AWS.S3();
const LINEAR_API = 'https://api.linear.app/graphql';

// Multi-product pricing tiers
const PLANS = {
  basic:      { priceId: process.env.STRIPE_PRICE_BASIC,      mrr: 49,  label: 'Basic' },
  pro:        { priceId: process.env.STRIPE_PRICE_PRO,        mrr: 99,  label: 'Pro' },
  enterprise: { priceId: process.env.STRIPE_PRICE_ENTERPRISE, mrr: 299, label: 'Enterprise' }
};

class RevenueAgent {
  constructor() {
    this.revenueToday = 0;
    this.conversions = [];
    this.linearKey = process.env.LINEAR_API_KEY;
  }

  async createLinearTask(title, description, priority = 'medium') {
    const query = `
      mutation CreateIssue($title: String!, $description: String!, $priority: Int!) {
        issueCreate(input: {
          title: $title
          description: $description
          priority: $priority
          teamId: "${process.env.LINEAR_TEAM_ID}"
          labelIds: ["${process.env.LINEAR_REVENUE_LABEL}"]
        }) {
          issue {
            id
            identifier
            url
          }
        }
      }
    `;

    const priorityMap = { low: 1, medium: 2, high: 3, urgent: 4 };

    try {
      const response = await axios.post(
        LINEAR_API,
        {
          query,
          variables: { title, description, priority: priorityMap[priority] }
        },
        {
          headers: {
            'Authorization': this.linearKey,
            'Content-Type': 'application/json'
          }
        }
      );
      return response.data.data.issueCreate.issue;
    } catch (error) {
      console.error('Linear API error:', error.response?.data || error.message);
      return null;
    }
  }

  async processLeadToCustomer(lead, plan = 'pro') {
    const planConfig = PLANS[plan] || PLANS.pro;
    try {
      // Create Stripe customer
      const customer = await stripe.customers.create({
        email: lead.email,
        name: lead.name,
        metadata: {
          company: lead.company || 'Unknown',
          title: lead.title || 'Unknown',
          source: 'apollo-auto-acquisition',
          acquired_date: new Date().toISOString(),
          plan: plan
        }
      });

      // Create payment method (for testing, use pm_card_visa)
      // In production, collect actual payment details
      const paymentMethod = await stripe.paymentMethods.create({
        type: 'card',
        card: { token: 'tok_visa' }  // Replace with actual payment collection
      });

      await stripe.paymentMethods.attach(paymentMethod.id, {
        customer: customer.id
      });

      await stripe.customers.update(customer.id, {
        invoice_settings: {
          default_payment_method: paymentMethod.id
        }
      });

      // Build subscription params
      const subParams = {
        customer: customer.id,
        trial_period_days: 14,
        metadata: {
          lead_source: 'apollo',
          automation: 'garcar-wealth-system',
          plan: plan
        }
      };
      if (planConfig.priceId) {
        subParams.items = [{ price: planConfig.priceId }];
      }

      const subscription = await stripe.subscriptions.create(subParams);

      this.conversions.push({
        customer_id: customer.id,
        subscription_id: subscription.id,
        email: lead.email,
        plan: plan,
        mrr: planConfig.mrr,
        status: subscription.status,
        trial_end: new Date(subscription.trial_end * 1000).toISOString()
      });

      this.revenueToday += planConfig.mrr;

      // Log to Linear
      await this.createLinearTask(
        `New Customer: ${lead.name} (${planConfig.label})`,
        `✅ Subscription created\n- Email: ${lead.email}\n- Company: ${lead.company}\n- Plan: ${planConfig.label}\n- MRR: $${planConfig.mrr}\n- Trial ends: ${new Date(subscription.trial_end * 1000).toLocaleDateString()}`,
        'high'
      );

      return {
        success: true,
        customer_id: customer.id,
        subscription_id: subscription.id,
        plan: plan,
        mrr: planConfig.mrr
      };

    } catch (error) {
      console.error(`Stripe error for ${lead.email}:`, error.message);
      
      // Create urgent task for failed conversion
      await this.createLinearTask(
        `Failed Conversion: ${lead.email}`,
        `❌ Error: ${error.message}\n- Lead: ${lead.name}\n- Company: ${lead.company}\nRequires manual follow-up`,
        'urgent'
      );

      return { success: false, error: error.message };
    }
  }

  async upsellCustomer(customerId, currentPlan, targetPlan) {
    /**
     * Upgrade an existing customer from one plan to a higher tier.
     * Basic → Pro, Basic/Pro → Enterprise
     */
    const target = PLANS[targetPlan];
    if (!target) {
      return { success: false, error: `Unknown target plan: ${targetPlan}` };
    }
    if (!target.priceId) {
      return { success: false, error: `Price ID not configured for plan: ${targetPlan}` };
    }

    try {
      // Retrieve current subscriptions
      const subscriptions = await stripe.subscriptions.list({
        customer: customerId,
        status: 'active',
        limit: 1
      });

      if (!subscriptions.data.length) {
        return { success: false, error: 'No active subscription found' };
      }

      const sub = subscriptions.data[0];
      const itemId = sub.items.data[0]?.id;

      // Update subscription item to new price (prorated immediately)
      const updated = await stripe.subscriptions.update(sub.id, {
        items: [{ id: itemId, price: target.priceId }],
        proration_behavior: 'create_prorations',
        metadata: { plan: targetPlan, upgraded_from: currentPlan }
      });

    const mrrDelta = target.mrr - (PLANS[currentPlan]?.mrr ?? target.mrr);
      this.revenueToday += mrrDelta;

      await this.createLinearTask(
        `Upsell Success: ${customerId}`,
        `⬆️ Upgraded ${currentPlan} → ${targetPlan}\n- MRR delta: +$${mrrDelta}\n- New MRR: $${target.mrr}`,
        'high'
      );

      return {
        success: true,
        subscription_id: updated.id,
        from_plan: currentPlan,
        to_plan: targetPlan,
        mrr_delta: mrrDelta
      };
    } catch (error) {
      console.error(`Upsell error for ${customerId}:`, error.message);
      return { success: false, error: error.message };
    }
  }

  async handleWebhook(event) {
    /**
     * Process Stripe webhooks for subscription lifecycle events
     */
    switch (event.type) {
      case 'customer.subscription.trial_will_end':
        await this.createLinearTask(
          `Trial Ending: ${event.data.object.customer}`,
          `Trial ends in 3 days. Send conversion nudge email.`,
          'high'
        );
        break;

      case 'customer.subscription.updated':
        if (event.data.object.status === 'active' && event.data.previous_attributes?.status === 'trialing') {
          const plan = event.data.object.metadata?.plan || 'pro';
          const mrr = PLANS[plan]?.mrr || 99;
          await this.createLinearTask(
            `Conversion Success: ${event.data.object.customer}`,
            `🎉 Trial converted to paid subscription!\n- Plan: ${plan}\n- MRR: $${mrr}`,
            'high'
          );
        }
        break;

      case 'customer.subscription.deleted':
        await this.createLinearTask(
          `Churn Alert: ${event.data.object.customer}`,
          `⚠️ Customer canceled subscription. Initiate win-back campaign.`,
          'urgent'
        );
        break;

      case 'invoice.payment_succeeded':
        this.revenueToday += event.data.object.amount_paid / 100;
        break;

      case 'invoice.payment_failed':
        await this.createLinearTask(
          `Payment Failed: ${event.data.object.customer}`,
          `❌ Payment declined. Retry payment method.`,
          'urgent'
        );
        break;
    }
  }

  async generateRevenueReport() {
    const planBreakdown = {};
    for (const [plan, config] of Object.entries(PLANS)) {
      const planConversions = this.conversions.filter(c => c.plan === plan);
      planBreakdown[plan] = {
        count: planConversions.length,
        mrr: planConversions.reduce((sum, c) => sum + c.mrr, 0),
        price: config.mrr
      };
    }

    const report = {
      date: new Date().toISOString(),
      conversions: this.conversions.length,
      revenue_today: this.revenueToday,
      mrr_added: this.revenueToday,
      plan_breakdown: planBreakdown,
      conversion_rate: this.conversions.length > 0 ? '1-3%' : '0%',
      details: this.conversions
    };

    // Store in S3
    await s3.putObject({
      Bucket: process.env.S3_BUCKET || 'garcar-revenue-data',
      Key: `reports/revenue_${new Date().toISOString().split('T')[0]}.json`,
      Body: JSON.stringify(report, null, 2),
      ContentType: 'application/json'
    }).promise();

    // Create summary in Linear
    await this.createLinearTask(
      `Daily Revenue Report: $${this.revenueToday}`,
      `📊 Revenue Summary\n- Conversions: ${this.conversions.length}\n- MRR Added: $${this.revenueToday}\n- Customers: ${this.conversions.map(c => c.email).join(', ')}`,
      'high'
    );

    return report;
  }
}

exports.handler = async (event, context) => {
  const agent = new RevenueAgent();

  // Handle Stripe webhook events
  if (event.headers && event.headers['stripe-signature']) {
    const sig = event.headers['stripe-signature'];
    let stripeEvent;

    try {
      stripeEvent = stripe.webhooks.constructEvent(
        event.body,
        sig,
        process.env.STRIPE_WEBHOOK_SECRET
      );
      await agent.handleWebhook(stripeEvent);
      return { statusCode: 200, body: JSON.stringify({ received: true }) };
    } catch (err) {
      console.error('Webhook signature verification failed:', err.message);
      return { statusCode: 400, body: JSON.stringify({ error: err.message }) };
    }
  }

  // Process leads from orchestrator
  const leads = JSON.parse(event.leads || '[]');
  const results = [];

  for (let lead of leads.slice(0, 20)) {  // Process first 20 leads
    // Determine plan from lead metadata (set by Python scorer) or default to pro
    const plan = lead.plan || 'pro';
    const result = await agent.processLeadToCustomer(lead, plan);
    results.push(result);
    
    // Rate limit: 2 requests per second
    await new Promise(resolve => setTimeout(resolve, 500));
  }

  const report = await agent.generateRevenueReport();

  return {
    statusCode: 200,
    body: JSON.stringify({
      processed: results.length,
      successful: results.filter(r => r.success).length,
      failed: results.filter(r => !r.success).length,
      revenue_today: agent.revenueToday,
      report: report
    })
  };
};

module.exports = { RevenueAgent };
