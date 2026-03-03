"""Apollo.io API Integration for B2B Lead Generation
Automated prospecting for enterprise AI/automation buyers
"""
import requests
import os
import json
from typing import List, Dict
from datetime import datetime

class ApolloLeadGen:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.apollo.io/v1"
        self.headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": self.api_key
        }
    
    def search_leads(self, 
                     query: str = "AI automation",
                     titles: List[str] = None,
                     employee_range: str = "50-500",
                     limit: int = 100) -> List[Dict]:
        """Search for qualified B2B leads matching criteria"""
        
        if titles is None:
            titles = [
                "CEO", "CTO", "Chief Technology Officer",
                "VP Engineering", "Head of AI", "Director of Technology",
                "VP Product", "Chief Product Officer"
            ]
        
        payload = {
            "q_keywords": query,
            "person_titles": titles,
            "organization_num_employees_ranges": [employee_range],
            "per_page": min(limit, 100),  # Apollo API limit
            "page": 1,
            # Target tech-forward companies
            "person_seniorities": ["executive", "vp", "director"],
            "organization_industry_tag_ids": [
                "5567cd4773696439b10b0000",  # Software
                "5567cd4773696439b1180000",  # Information Technology
                "5567cd4773696439b11c0000"   # Computer Software
            ]
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/mixed_people/search",
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            
            data = response.json()
            leads = []
            
            for person in data.get('people', []):
                lead = {
                    'name': person.get('name'),
                    'email': person.get('email'),
                    'title': person.get('title'),
                    'company': person.get('organization_name'),
                    'company_domain': person.get('organization', {}).get('primary_domain'),
                    'employee_range': person.get('organization', {}).get('estimated_num_employees'),
                    'industry': person.get('organization', {}).get('industry'),
                    'linkedin': person.get('linkedin_url'),
                    'phone': person.get('phone_numbers', [{}])[0].get('sanitized_number') if person.get('phone_numbers') else None,
                    'technologies': person.get('organization', {}).get('technologies', []),
                    'acquired_at': datetime.now().isoformat(),
                    'source': 'apollo-api'
                }
                
                # Only include leads with valid email
                if lead['email']:
                    leads.append(lead)
            
            return leads
            
        except requests.exceptions.RequestException as e:
            print(f"Apollo API error: {str(e)}")
            return []
    
    def enrich_lead(self, email: str) -> Dict:
        """Enrich existing lead data with additional Apollo information"""
        payload = {"email": email}
        
        try:
            response = requests.post(
                f"{self.base_url}/people/match",
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            return response.json().get('person', {})
        except requests.exceptions.RequestException as e:
            print(f"Apollo enrichment error: {str(e)}")
            return {}
    
    def get_account_info(self, domain: str) -> Dict:
        """Get detailed company/account information"""
        payload = {"domain": domain}
        
        try:
            response = requests.post(
                f"{self.base_url}/organizations/enrich",
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            return response.json().get('organization', {})
        except requests.exceptions.RequestException as e:
            print(f"Apollo account lookup error: {str(e)}")
            return {}
    
    def bulk_enrich(self, leads: List[Dict]) -> List[Dict]:
        """Enrich multiple leads with additional data"""
        enriched = []
        
        for lead in leads:
            if lead.get('email'):
                enrichment = self.enrich_lead(lead['email'])
                lead.update({
                    'enriched': True,
                    'enriched_at': datetime.now().isoformat(),
                    'additional_data': enrichment
                })
            enriched.append(lead)
        
        return enriched

# Standalone testing
if __name__ == "__main__":
    api_key = os.environ.get('APOLLO_API_KEY')
    if not api_key:
        print("Error: APOLLO_API_KEY environment variable not set")
        exit(1)
    
    apollo = ApolloLeadGen(api_key)
    
    # Test search
    leads = apollo.search_leads(
        query="AI automation enterprise",
        titles=["CTO", "VP Engineering"],
        employee_range="100-500",
        limit=10
    )
    
    print(f"Found {len(leads)} qualified leads:")
    print(json.dumps(leads[:3], indent=2))  # Print first 3
