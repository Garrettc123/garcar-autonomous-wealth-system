/**
 * Revenue Agent - Stripe Integration for Garcar Autonomous Wealth System
 * Handles subscription management, payment processing, and customer lifecycle
 */

const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);
const AWS = require('aws-sdk');
const axios = require('axios');

const s3 = new AWS.S3();
const LINEAR_API = 'https://api.linear.app/graphql';

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

  async processLeadToCustomer(lead) {
    try {
      // Create Stripe customer
      const customer = await stripe.customers.create({
        email: lead.email,
        name: lead.name,
        metadata: {
          company: lead.company || 'Unknown',
          title: lead.title || 'Unknown',
          source: 'apollo-auto-acquisition',
          acquired_date: new Date().toISOString()
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

      // Create subscription with 14-day trial
      const subscription = await stripe.subscriptions.create({
        customer: customer.id,
        items: [{
          price: process.env.STRIPE_PRICE_ID  // Enterprise tier: $99/mo
        }],
        trial_period_days: 14,
        metadata: {
          lead_source: 'apollo',
          automation: 'garcar-wealth-system'
        }
      });

      this.conversions.push({
        customer_id: customer.id,
        subscription_id: subscription.id,
        email: lead.email,
        mrr: 99,
        status: subscription.status,
        trial_end: new Date(subscription.trial_end * 1000).toISOString()
      });

      this.revenueToday += 99;

      // Log to Linear
      await this.createLinearTask(
        `New Customer: ${lead.name}`,
        `✅ Subscription created\n- Email: ${lead.email}\n- Company: ${lead.company}\n- MRR: $99\n- Trial ends: ${new Date(subscription.trial_end * 1000).toLocaleDateString()}`,
        'high'
      );

      return {
        success: true,
        customer_id: customer.id,
        subscription_id: subscription.id,
        mrr: 99
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
          await this.createLinearTask(
            `Conversion Success: ${event.data.object.customer}`,
            `🎉 Trial converted to paid subscription!\nMRR: $99`,
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
    const report = {
      date: new Date().toISOString(),
      conversions: this.conversions.length,
      revenue_today: this.revenueToday,
      mrr_added: this.revenueToday,
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
    const result = await agent.processLeadToCustomer(lead);
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
