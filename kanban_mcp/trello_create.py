#!/usr/bin/env python3
"""
Create new Trello boards and manage bidirectional sync
Safe tools that only create/modify designated boards
"""
import os
import json
import requests
from typing import Dict, List, Any, Optional
from datetime import datetime
from .trello_sync import TrelloClient

class TrelloBoardManager:
    """Manages creation and bidirectional sync of Trello boards"""

    def __init__(self):
        self.client = TrelloClient()

    def create_board(self, name: str, description: str = "") -> Dict[str, Any]:
        """Create a new Trello board"""
        try:
            endpoint = "/boards"
            params = {
                'name': name,
                'desc': description,
                'defaultLists': 'false'  # We'll create our own lists
            }

            board = self.client._request(endpoint, method='POST', params=params)

            # Create standard kanban lists
            standard_lists = [
                'Backlog',
                'Current Sprint',
                'In Progress',
                'Blocked',
                'Done',
                'Archived'
            ]

            for list_name in standard_lists:
                self._create_list(board['id'], list_name)

            return {
                "status": "success",
                "board": board,
                "message": f"Created board '{name}' with {len(standard_lists)} lists"
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to create board: {str(e)}"
            }

    def _create_list(self, board_id: str, name: str) -> Dict[str, Any]:
        """Create a list on a Trello board"""
        endpoint = f"/boards/{board_id}/lists"
        params = {'name': name}
        return self.client._request(endpoint, method='POST', params=params)

    def create_card(self, board_id: str, list_name: str, title: str, description: str = "", assignee: str = "") -> Dict[str, Any]:
        """Create a card on a Trello board"""
        try:
            # Get the list ID for the target list
            lists = self.client.get_lists(board_id)
            target_list = None

            for tlist in lists:
                if tlist['name'].lower() == list_name.lower():
                    target_list = tlist
                    break

            if not target_list:
                return {
                    "status": "error",
                    "message": f"List '{list_name}' not found on board"
                }

            # Create the card
            endpoint = "/cards"
            params = {
                'name': title,
                'desc': description,
                'idList': target_list['id']
            }

            card = self.client._request(endpoint, method='POST', params=params)

            return {
                "status": "success",
                "card": card,
                "message": f"Created card '{title}' in '{list_name}'"
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to create card: {str(e)}"
            }

    def move_card(self, card_id: str, list_name: str, board_id: str) -> Dict[str, Any]:
        """Move a card to a different list"""
        try:
            # Get the list ID for the target list
            lists = self.client.get_lists(board_id)
            target_list = None

            for tlist in lists:
                if tlist['name'].lower() == list_name.lower():
                    target_list = tlist
                    break

            if not target_list:
                return {
                    "status": "error",
                    "message": f"List '{list_name}' not found on board"
                }

            # Move the card
            endpoint = f"/cards/{card_id}"
            params = {'idList': target_list['id']}

            card = self.client._request(endpoint, method='PUT', params=params)

            return {
                "status": "success",
                "card": card,
                "message": f"Moved card to '{list_name}'"
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to move card: {str(e)}"
            }

    def sync_to_trello(self, db, board_id: str, trello_board_id: str) -> Dict[str, Any]:
        """
        Sync kanban-mcp cards TO Trello (write-back)
        ONLY works with boards explicitly marked as bidirectional
        """
        try:
            # Safety check - only sync boards with specific naming pattern
            trello_board = self.client._request(f"/boards/{trello_board_id}", params={'fields': 'name'})

            if 'BRO Partnership' not in trello_board['name']:
                return {
                    "status": "error",
                    "message": f"Safety check failed: Board '{trello_board['name']}' not marked for bidirectional sync"
                }

            # Get kanban-mcp cards
            kanban_cards = db.list_cards(board_id)

            # Get existing Trello cards
            trello_cards = self.client.get_cards(trello_board_id)
            trello_card_map = {card['name']: card for card in trello_cards}

            synced = 0
            errors = []

            for kanban_card in kanban_cards:
                try:
                    # Skip cards that originated from Trello
                    if kanban_card.get('external_type') == 'trello':
                        continue

                    title = kanban_card['title']
                    column = kanban_card.get('column', 'backlog')

                    # Map kanban column to Trello list name
                    trello_list_name = self._map_column_to_trello_list(column)

                    if title in trello_card_map:
                        # Card exists - check if it needs to move
                        trello_card = trello_card_map[title]
                        current_list_id = trello_card['idList']

                        # Get current list name
                        lists = self.client.get_lists(trello_board_id)
                        current_list_name = None
                        for tlist in lists:
                            if tlist['id'] == current_list_id:
                                current_list_name = tlist['name']
                                break

                        if current_list_name and current_list_name.lower() != trello_list_name.lower():
                            # Move card
                            result = self.move_card(trello_card['id'], trello_list_name, trello_board_id)
                            if result['status'] == 'success':
                                synced += 1
                    else:
                        # Create new card
                        result = self.create_card(
                            trello_board_id,
                            trello_list_name,
                            title,
                            kanban_card.get('description', ''),
                            kanban_card.get('assignee', '')
                        )
                        if result['status'] == 'success':
                            synced += 1

                except Exception as e:
                    errors.append(f"Card {kanban_card['title']}: {str(e)}")

            return {
                "status": "success",
                "synced": synced,
                "errors": errors,
                "message": f"Synced {synced} cards to Trello board"
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Sync to Trello failed: {str(e)}"
            }

    def _map_column_to_trello_list(self, column: str) -> str:
        """Map kanban-mcp column names to Trello list names"""
        mapping = {
            'backlog': 'Backlog',
            'current_sprint': 'Current Sprint',
            'in_progress': 'In Progress',
            'blocked': 'Blocked',
            'done': 'Done',
            'archived': 'Archived'
        }
        return mapping.get(column, 'Backlog')

# Function to create the BRO Partnership board
def create_bro_partnership_board() -> Dict[str, Any]:
    """Create the dedicated BRO Partnership Trello board"""
    manager = TrelloBoardManager()

    return manager.create_board(
        name="BRO Partnership Board",
        description="AI/Human partnership tasks and coordination. Safe for bidirectional sync with kanban-mcp."
    )