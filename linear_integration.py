"""Linear.app Integration for Task Tracking and Workflow Automation
Automates issue creation, updates, and project management for Garcar Enterprise
"""
import requests
import os
import json
from typing import Dict, List, Optional
from datetime import datetime

class LinearTracker:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.linear.app/graphql"
        self.headers = {
            "Authorization": api_key,
            "Content-Type": "application/json"
        }
        self.team_id = os.environ.get('LINEAR_TEAM_ID', '')
    
    def _execute_query(self, query: str, variables: Dict = None) -> Dict:
        """Execute GraphQL query against Linear API"""
        try:
            response = requests.post(
                self.base_url,
                headers=self.headers,
                json={"query": query, "variables": variables or {}}
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Linear API error: {str(e)}")
            return {"errors": [str(e)]}
    
    def get_team_id(self) -> str:
        """Get first team ID if not configured"""
        if self.team_id:
            return self.team_id
        
        query = """
        query {
          teams {
            nodes {
              id
              name
            }
          }
        }
        """
        result = self._execute_query(query)
        teams = result.get('data', {}).get('teams', {}).get('nodes', [])
        if teams:
            self.team_id = teams[0]['id']
            return self.team_id
        return ""
    
    def create_task(self, 
                    title: str,
                    description: str = "",
                    priority: str = "medium",
                    labels: List[str] = None,
                    assignee_id: str = None) -> Dict:
        """Create new issue/task in Linear"""
        
        # Ensure we have team ID
        if not self.team_id:
            self.get_team_id()
        
        priority_map = {
            "urgent": 1,
            "high": 2,
            "medium": 3,
            "low": 4
        }
        
        query = """
        mutation IssueCreate($input: IssueCreateInput!) {
          issueCreate(input: $input) {
            success
            issue {
              id
              identifier
              title
              url
              createdAt
            }
          }
        }
        """
        
        variables = {
            "input": {
                "teamId": self.team_id,
                "title": title,
                "description": description,
                "priority": priority_map.get(priority, 3)
            }
        }
        
        if assignee_id:
            variables["input"]["assigneeId"] = assignee_id
        
        # Note: Label management requires label IDs, not names
        # You'll need to fetch/create labels separately
        
        result = self._execute_query(query, variables)
        
        if result.get('data', {}).get('issueCreate', {}).get('success'):
            issue = result['data']['issueCreate']['issue']
            print(f"✅ Created Linear task: {issue['identifier']} - {title}")
            return issue
        else:
            print(f"❌ Failed to create Linear task: {result.get('errors')}")
            return {}
    
    def update_task(self,
                    task_id: str,
                    state: str = None,
                    description: str = None,
                    priority: str = None) -> Dict:
        """Update existing Linear issue"""
        
        query = """
        mutation IssueUpdate($id: String!, $input: IssueUpdateInput!) {
          issueUpdate(id: $id, input: $input) {
            success
            issue {
              id
              identifier
              title
              state {
                name
              }
            }
          }
        }
        """
        
        update_input = {}
        
        if description:
            update_input["description"] = description
        
        if priority:
            priority_map = {"urgent": 1, "high": 2, "medium": 3, "low": 4}
            update_input["priority"] = priority_map.get(priority, 3)
        
        if state:
            # Get state ID by name
            state_id = self._get_state_id(state)
            if state_id:
                update_input["stateId"] = state_id
        
        variables = {
            "id": task_id,
            "input": update_input
        }
        
        result = self._execute_query(query, variables)
        
        if result.get('data', {}).get('issueUpdate', {}).get('success'):
            return result['data']['issueUpdate']['issue']
        else:
            print(f"Failed to update task: {result.get('errors')}")
            return {}
    
    def _get_state_id(self, state_name: str) -> Optional[str]:
        """Get workflow state ID by name"""
        query = f"""
        query {{
          team(id: "{self.team_id}") {{
            states {{
              nodes {{
                id
                name
              }}
            }}
          }}
        }}
        """
        
        result = self._execute_query(query)
        states = result.get('data', {}).get('team', {}).get('states', {}).get('nodes', [])
        
        for state in states:
            if state['name'].lower() == state_name.lower():
                return state['id']
        return None
    
    def create_project(self, name: str, description: str = "") -> Dict:
        """Create new project in Linear"""
        query = """
        mutation ProjectCreate($input: ProjectCreateInput!) {
          projectCreate(input: $input) {
            success
            project {
              id
              name
              url
            }
          }
        }
        """
        
        variables = {
            "input": {
                "name": name,
                "description": description,
                "teamIds": [self.team_id]
            }
        }
        
        result = self._execute_query(query, variables)
        
        if result.get('data', {}).get('projectCreate', {}).get('success'):
            return result['data']['projectCreate']['project']
        return {}
    
    def get_issues(self, state: str = None, limit: int = 50) -> List[Dict]:
        """Fetch issues from Linear"""
        query = f"""
        query {{
          issues(first: {limit}, filter: {{ team: {{ id: {{ eq: "{self.team_id}" }} }} }}) {{
            nodes {{
              id
              identifier
              title
              description
              priority
              state {{
                name
              }}
              assignee {{
                name
              }}
              createdAt
              updatedAt
              url
            }}
          }}
        }}
        """
        
        result = self._execute_query(query)
        return result.get('data', {}).get('issues', {}).get('nodes', [])
    
    def create_comment(self, issue_id: str, body: str) -> Dict:
        """Add comment to Linear issue"""
        query = """
        mutation CommentCreate($input: CommentCreateInput!) {
          commentCreate(input: $input) {
            success
            comment {
              id
              body
            }
          }
        }
        """
        
        variables = {
            "input": {
                "issueId": issue_id,
                "body": body
            }
        }
        
        result = self._execute_query(query, variables)
        if result.get('data', {}).get('commentCreate', {}).get('success'):
            return result['data']['commentCreate']['comment']
        return {}

# Standalone testing
if __name__ == "__main__":
    api_key = os.environ.get('LINEAR_API_KEY')
    if not api_key:
        print("Error: LINEAR_API_KEY environment variable not set")
        exit(1)
    
    linear = LinearTracker(api_key)
    
    # Test task creation
    task = linear.create_task(
        title="Test: Autonomous Wealth System Integration",
        description="Testing Linear API integration for revenue tracking",
        priority="high",
        labels=["automation", "test"]
    )
    
    print(f"Created task: {json.dumps(task, indent=2)}")
