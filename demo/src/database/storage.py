import sqlite3
import json
from pathlib import Path
from typing import Dict, List, Any
from src.llm.rank import CodeComponent

CURRENT_DIR = Path(__file__).parent

class Storage:
    """A lightweight database manager that stores heavy codebase dictionaries
       on disk to free up RAM for LLM execution."""

    def __init__(self, db_path: str = "database.db"):
        self.db_path = CURRENT_DIR / db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Create the table if it does not exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS components (
                    id TEXT PRIMARY KEY,
                    data JSON
                )
            ''')
            conn.commit()

    def save(self, components_dict: Dict[str, Any]):
        """Saves a dictionary of CodeComponent serializations to the database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for comp_id, comp_data in components_dict.items():
                cursor.execute(
                    '''INSERT OR REPLACE INTO components (id, data) VALUES (?, ?)''',
                    (comp_id, json.dumps(comp_data))
                )
            conn.commit()

    def get(self, comp_id: str) -> dict:
        """Fetch a single component from the database without loading the whole repo."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('SELECT data FROM components WHERE id = ?', (comp_id,))
            row = cursor.fetchone()
            if row:
                return CodeComponent.from_dict(json.loads(row[0]))
            return {}

    def get_batch(self, comp_ids: List[str]) -> List[dict]:
        """Fetch exactly the batch of components needed for the current LLM prompt."""
        if not comp_ids:
            return []
        
        placeholders = ','.join(['?'] * len(comp_ids))
        query = f'SELECT data FROM components WHERE id IN ({placeholders})'
        
        with sqlite3.connect(self.db_path) as conn:
            # We must pass the comp_ids as the tuple/list for the placeholders
            cursor = conn.execute(query, comp_ids)
            return [CodeComponent.from_dict(json.loads(row[0])) for row in cursor.fetchall()]

    def get_all_topologies(self) -> Dict[str, List[str]]:
        """A lightweight query to extract ONLY the dependency edges to build the graph,
           ignoring the heavy source codes."""
        topology = {}
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('SELECT id, data FROM components')
            for row in cursor:
                comp_id = row[0]
                data = json.loads(row[1])
                topology[comp_id] = data.get("depends_on", [])
        return topology
