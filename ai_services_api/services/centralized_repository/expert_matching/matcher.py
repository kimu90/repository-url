from typing import List, Dict
from ai_services_api.services.centralized_repository.expert_matching.models import Expert, Resource
from ai_services_api.services.centralized_repository.expert_matching.logger import Logger
from ai_services_api.services.centralized_repository.database_setup import get_db_cursor
import json

class Matcher:
    """Matches experts with resources based on author names"""
    
    def __init__(self):
        self.name_cache = {}
        self.logger = Logger(__name__)

    def _normalize_name(self, name: str) -> str:
        """Normalize author name for comparison"""
        return ' '.join(str(name).lower().split())

    def match_experts_to_resources(self, experts: List[Dict], resources: List[Dict]) -> Dict[int, List[int]]:
        """Match experts to resources based on author names."""
        try:
            matches = {}
            
            # Build expert name lookup
            expert_lookup = {}
            for expert in experts:
                if isinstance(expert, tuple):
                    # Get id and name fields from tuple, accounting for different lengths
                    expert_id = expert[0]  # ID is always first
                    # First and last name are in positions 1 and 2
                    first_name = expert[1] if len(expert) > 1 else ''
                    last_name = expert[2] if len(expert) > 2 else ''
                    full_name = self._normalize_name(f"{first_name} {last_name}")
                    expert_lookup[full_name] = expert_id
                else:
                    # Handle dictionary input
                    expert_lookup[self._normalize_name(expert['name'])] = expert['id']
            
            # Match resources to experts
            for resource in resources:
                try:
                    if isinstance(resource, tuple):
                        # Handle database tuple result - expect (id, authors)
                        resource_id = resource[0]
                        authors = resource[1]
                        
                        # Handle different author data formats
                        if isinstance(authors, str):
                            if not authors.strip():  # Handle empty strings
                                author_list = []
                            else:
                                try:
                                    author_list = json.loads(authors)
                                except json.JSONDecodeError:
                                    # If JSON parsing fails, try treating as single author
                                    author_list = [authors]
                        elif isinstance(authors, list):
                            author_list = authors
                        elif authors is None:
                            author_list = []
                        else:
                            # Try converting to string if other type
                            author_list = [str(authors)]
                    else:
                        # Handle dictionary input
                        resource_id = resource['id']
                        author_list = resource.get('authors', [])
                        if isinstance(author_list, str):
                            try:
                                author_list = json.loads(author_list)
                            except json.JSONDecodeError:
                                author_list = [author_list]
                    
                    # Skip empty author lists
                    if not author_list:
                        continue
                        
                    # Process each author
                    for author in author_list:
                        if not author:  # Skip empty author names
                            continue
                        normalized_name = self._normalize_name(author)
                        if normalized_name in expert_lookup:
                            expert_id = expert_lookup[normalized_name]
                            if expert_id not in matches:
                                matches[expert_id] = []
                            matches[expert_id].append(resource_id)
                                
                except (KeyError, TypeError) as e:
                    self.logger.warning(f"Skipping malformed resource {resource_id if 'resource_id' in locals() else 'unknown'}: {e}")
                    continue
            
            self.logger.info(f"Found {len(matches)} expert-resource matches")
            return matches
            
        except Exception as e:
            self.logger.error(f"Error matching experts to resources: {e}")
            raise

    def link_matched_experts_to_db(self) -> None:
        """Link matched experts to resources in database"""
        try:
            with get_db_cursor() as (cur, conn):
                # Get all experts
                cur.execute("""
                    SELECT id, first_name, last_name 
                    FROM experts_expert
                    WHERE is_active = TRUE
                """)
                experts = cur.fetchall()

                # Get all resources
                cur.execute("""
                    SELECT id, authors 
                    FROM resources_resource 
                    WHERE authors IS NOT NULL
                """)
                resources = cur.fetchall()

                # Get matches using tuple data directly
                matches = self.match_experts_to_resources(experts, resources)

                # Store matches in database
                for expert_id, resource_ids in matches.items():
                    for resource_id in resource_ids:
                        cur.execute("""
                            INSERT INTO expert_resource_links 
                                (expert_id, resource_id, confidence_score)
                            VALUES (%s, %s, 1.0)
                            ON CONFLICT (expert_id, resource_id) DO NOTHING
                        """, (expert_id, resource_id))

            conn.commit()
            self.logger.info(f"Successfully linked {len(matches)} experts to resources")

        except Exception as e:
            self.logger.error(f"Error linking experts to resources: {e}")
            raise
