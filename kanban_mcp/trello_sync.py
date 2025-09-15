#!/usr/bin/env python3
"""
Trello sync integration for kanban-mcp
Uses the same pattern as story sync but talks to Trello API
"""
import os
import json
import requests
from typing import Dict, List, Any, Optional
from datetime import datetime

class TrelloClient:
    """Simple Trello API client"""

    def __init__(self):
        self.api_key = os.getenv('TRELLO_API_KEY')
        self.token = os.getenv('TRELLO_TOKEN')
        self.base_url = "https://api.trello.com/1"

        if not self.api_key or not self.token:
            raise ValueError("Missing TRELLO_API_KEY or TRELLO_TOKEN in environment")

    def _request(self, endpoint: str, method: str = 'GET', params: dict = None) -> dict:
        """Make authenticated request to Trello API"""
        url = f"{self.base_url}{endpoint}"

        # Add auth to params
        params = params or {}
        params.update({
            'key': self.api_key,
            'token': self.token
        })

        response = requests.request(method, url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()

    def get_boards(self) -> List[Dict[str, Any]]:
        """Get all boards for current user"""
        return self._request('/members/me/boards', params={'fields': 'name,id'})

    def get_board_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Find board by name"""
        boards = self.get_boards()
        for board in boards:
            if board['name'] == name:
                return board
        return None

    def get_lists(self, board_id: str) -> List[Dict[str, Any]]:
        """Get all lists (columns) for a board"""
        return self._request(f'/boards/{board_id}/lists', params={'fields': 'name,id'})

    def get_cards(self, board_id: str) -> List[Dict[str, Any]]:
        """Get all cards for a board"""
        return self._request(f'/boards/{board_id}/cards', params={
            'fields': 'name,desc,idList,dateLastActivity,id'
        })

def sync_from_trello(db, board_id: str, trello_board_name: str) -> Dict[str, Any]:
    """
    Sync cards from Trello board to kanban-mcp
    Following the pattern from sync_from_story
    """
    if not os.getenv('TRELLO_SYNC_ENABLE'):
        return {"status": "disabled", "message": "TRELLO_SYNC_ENABLE not set"}

    try:
        client = TrelloClient()

        # Find the Trello board
        trello_board = client.get_board_by_name(trello_board_name)
        if not trello_board:
            return {"status": "error", "message": f"Trello board '{trello_board_name}' not found"}

        # Get Trello lists and cards
        trello_lists = client.get_lists(trello_board['id'])
        trello_cards = client.get_cards(trello_board['id'])

        # Create mapping of list IDs to names
        list_mapping = {tlist['id']: tlist['name'] for tlist in trello_lists}

        # Sync cards
        synced = 0
        errors = []

        for trello_card in trello_cards:
            try:
                # Map Trello list to kanban column
                trello_list_name = list_mapping.get(trello_card['idList'], 'backlog')
                kanban_column = map_trello_list_to_column(trello_list_name)

                # Check if card already exists (filter by external_type and external_id)
                all_cards = db.list_cards(board_id)
                existing_cards = [c for c in all_cards if c.get('external_type') == 'trello' and c.get('external_id') == trello_card['id']]

                if existing_cards:
                    # Update existing card
                    card = existing_cards[0]
                    # Move to correct column if needed
                    if card['column'] != kanban_column:
                        db.move_card(card['id'], kanban_column)
                else:
                    # Create new card
                    db.add_card(
                        board_id=board_id,
                        title=trello_card['name'],
                        column=kanban_column,
                        description=trello_card.get('desc', ''),
                        external_type='trello',
                        external_id=trello_card['id']
                    )

                synced += 1

            except Exception as e:
                errors.append(f"Card {trello_card['name']}: {str(e)}")

        return {
            "status": "success",
            "synced": synced,
            "errors": errors,
            "trello_board": trello_board['name'],
            "trello_board_id": trello_board['id']
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}

def map_trello_list_to_column(trello_list_name: str) -> str:
    """
    Map Trello list names to kanban-mcp column names
    This is configurable - could be moved to env vars later
    """
    # Default mapping - customize as needed
    mapping = {
        'backlog': 'backlog',
        'to do': 'backlog',
        'doing': 'in_progress',
        'in progress': 'in_progress',
        'current sprint': 'current_sprint',
        'blocked': 'blocked',
        'done': 'done',
        'complete': 'done'
    }

    # Case-insensitive lookup
    lower_name = trello_list_name.lower()
    return mapping.get(lower_name, 'backlog')  # Default to backlog

# Test function for validation-mcp integration
def test_trello_sync(board_id: str, trello_board_name: str) -> Dict[str, Any]:
    """Test function that returns validation-mcp compatible result"""
    try:
        client = TrelloClient()
        board = client.get_board_by_name(trello_board_name)

        if not board:
            return {
                "strategy": "trello_sync",
                "passed": False,
                "score": 0,
                "details": f"Trello board '{trello_board_name}' not found",
                "ts": datetime.now().isoformat()
            }

        cards = client.get_cards(board['id'])

        return {
            "strategy": "trello_sync",
            "passed": True,
            "score": 100,
            "details": f"Found Trello board '{trello_board_name}' with {len(cards)} cards",
            "ts": datetime.now().isoformat(),
            "trello_board_id": board['id'],
            "card_count": len(cards)
        }

    except Exception as e:
        return {
            "strategy": "trello_sync",
            "passed": False,
            "score": 0,
            "details": f"Trello sync test failed: {str(e)}",
            "ts": datetime.now().isoformat()
        }