import collections
import json
import os

class CodeGraph:
    def __init__(self):
        self.nodes = {} 
        self.edges = [] 
        self.adjacency_list = collections.defaultdict(list)
        self.reverse_adjacency = collections.defaultdict(list)

    def add_node(self, name, node_type, filepath, start_line, end_line, **kwargs):
        """
        Stores METADATA only. No raw code in RAM.
        """
        self.nodes[name] = {
            "type": node_type, 
            "file": filepath,
            "start_line": start_line,
            "end_line": end_line,
            "doc_filepath": None, # Will store path to .json file later
            **kwargs
        }

    def add_relation(self, source, target, relation_type):
        edge = {"source": source, "target": target, "relation": relation_type}
        if edge not in self.edges:
            self.edges.append(edge)
            self.adjacency_list[source].append(target)
            self.reverse_adjacency[target].append(source)

    def set_doc_path(self, node_name, doc_path):
        if node_name in self.nodes:
            self.nodes[node_name]["doc_filepath"] = doc_path

    # --- LAZY LOADERS ---

    def fetch_source_code(self, node_name):
        """
        Reads the file from disk on-demand and extracts the specific lines.
        """
        node = self.nodes.get(node_name)
        if not node: return ""
        
        try:
            with open(node['file'], 'r', encoding='utf-8') as f:
                lines = f.readlines()
                # Adjust for 0-based index vs 1-based lineno
                start = node['start_line'] - 1
                end = node['end_line']
                return "".join(lines[start:end])
        except Exception as e:
            return f"Error reading source: {e}"

    def fetch_generated_doc(self, node_name):
        """
        Reads the previously generated JSON doc from disk.
        """
        node = self.nodes.get(node_name)
        if not node or not node.get('doc_filepath'): return None
        
        try:
            with open(node['doc_filepath'], 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def get_related_context_content(self, node_name):
        """
        Retrieves CONTENT of dependencies by reading from disk.
        """
        # Use defaultdict(list) so we don't crash on new relation types (e.g., 'uses_input')
        context = collections.defaultdict(list)
        
        for edge in self.edges:
            if edge["source"] == node_name:
                rel = edge["relation"]
                target = edge["target"]
                
                if target in self.nodes:
                    # OPTIMIZATION: Check for existing doc first
                    doc = self.fetch_generated_doc(target)
                    code = None
                    
                    # Only read raw code from disk if we don't have a compiled doc yet
                    if not doc:
                        code = self.fetch_source_code(target)
                    
                    context[rel].append({
                        "name": target,
                        "doc": doc,   # Parsed JSON or None
                        "code": code, # Raw string (only if doc is None)
                        "file": self.nodes[target]["file"]
                    })
        
        return context # Convert back to standard dict for callers


    def get_execution_order(self):
        visited = set()
        temp_mark = set()
        order = []

        def visit(node):
            if node in temp_mark: return 
            if node in visited: return
            temp_mark.add(node)
            # Only visit dependencies that exist in our graph
            for neighbor in self.adjacency_list[node]:
                if neighbor in self.nodes:
                    visit(neighbor)
            temp_mark.remove(node)
            visited.add(node)
            order.append(node)

        for node in list(self.nodes.keys()):
            if node not in visited:
                visit(node)
        return order