import json
import ollama
import math

# def ensure_model_downloaded(model_name):
def ensure_model_downloaded(model_name):
    """
    Checks if the model exists locally. If not, pulls it from the Ollama library.
    """
    print(f"Checking availability for model: '{model_name}'...")
    try:
        # List local models
        list_response = ollama.list()
        
        # 1. ROBUST PARSING of existing models
        # Some versions of ollama lib use 'name', others might use 'model'
        existing_models = []
        if 'models' in list_response:
            for m in list_response['models']:
                # Try 'name' first, then 'model'
                name = m.get('name') or m.get('model')
                if name:
                    existing_models.append(name)
        
        # Debug print if empty (helpful for troubleshooting)
        if not existing_models:
            print("   (Local model list appears empty or could not be parsed)")

        # 2. Check for match
        # Handle tags: user might ask for 'llama3', list might have 'llama3:latest'
        is_found = False
        for existing in existing_models:
            if model_name == existing or existing.startswith(f"{model_name}:"):
                is_found = True
                break
        
        if is_found:
            print(f"Model '{model_name}' is available locally.")
            return True
            
        # 3. Pull if not found
        print(f"Model '{model_name}' not found. Pulling from Ollama registry...")
        print(f"   (This may take a while depending on your internet connection)")
        
        # Stream the pull progress
        current_digest = ''
        for progress in ollama.pull(model_name, stream=True):
            # Simple progress bar logic
            status = progress.get('status', '')
            
            # Print status updates without flooding console
            # FIX: Rely on 'total' and 'completed' fields rather than status string text
            # We use 'or 0' because sometimes the API returns {'total': None}, which breaks > comparisons
            total = progress.get('total') or 0
            completed = progress.get('completed') or 0
            
            if total > 0:
                percent = (completed / total) * 100
                # padding spaces to overwrite previous longer lines
                print(f"\r   {status} - {percent:.1f}%   ", end='', flush=True)
            else:
                # For non-download statuses (verifying, writing, etc)
                print(f"\r   {status}   ", end='', flush=True)
                
        print(f"\nModel '{model_name}' pulled successfully.")
        return True
        
    except Exception as e:
        print(f"\nFailed to check/pull model '{model_name}'.")
        print(f"   Error Details: {e}")
        print("   Suggestion: Run 'ollama serve' in a separate terminal.")
        return False

def get_model_context_limit(model_name):
    """
    Dynamically fetches the context window size from Ollama.
    """
    try:
        info = ollama.show(model_name)
        
        # 1. Check explicit model info
        details = info.get('model_info', {})
        for key in ['llama.context_length', 'context_length', 'max_position_embeddings']:
            if key in details:
                print(f"Detected dynamic context limit for {model_name}: {details[key]}")
                return int(details[key])
        
        # 2. Check parameters
        params = info.get('parameters', '')
        if "num_ctx" in params:
            for line in params.split('\n'):
                if line.strip().startswith('num_ctx'):
                    val = int(line.split()[1])
                    print(f"Detected Modelfile context limit: {val}")
                    return val

        print(f"Could not detect context limit for {model_name}. Defaulting to 4096.")
        return 4096
        
    except Exception as e:
        print(f"Error fetching model info: {e}. Defaulting to 4096.")
        return 4096

def estimate_tokens(text):
    return len(text) / 4

def split_context_adaptively(context_text, max_window_size, reserved_tokens=1000):
    available_tokens = max_window_size - reserved_tokens
    if available_tokens < 500:
        available_tokens = 500 
        
    current_tokens = estimate_tokens(context_text)
    
    if current_tokens <= available_tokens:
        return [context_text]
    
    chunk_char_size = int(available_tokens * 4)
    chunks = []
    total_len = len(context_text)
    
    for i in range(0, total_len, chunk_char_size):
        chunk = context_text[i : i + chunk_char_size]
        part_msg = f"\n[PART {len(chunks)+1} - PARTIAL CONTEXT]\n"
        chunks.append(part_msg + chunk)
        
    return chunks

def query_ollama(model_name, system_prompt, user_prompt, context_data="", max_ctx=4096):
    """
    Now accepts max_ctx as an argument to avoid repeated API calls.
    """
    chunks = split_context_adaptively(context_data, max_window_size=max_ctx)
    
    final_context = chunks[0]
    if len(chunks) > 1:
        print(f"Input too large. Sending chunk 1 of {len(chunks)}.")

    full_user_message = user_prompt
    if context_data:
        full_user_message += f"\n\n--- CONTEXT ---\n{final_context}"

    try:
        response = ollama.chat(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": full_user_message}
            ],
            format="json", 
            options={
                "temperature": 0.1,
                "num_ctx": max_ctx 
            }
        )
        return json.loads(response['message']['content'])
    except Exception as e:
        print(f"LLM Error: {e}")
        return {}