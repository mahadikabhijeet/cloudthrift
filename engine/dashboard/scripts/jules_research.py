import os
import datetime
import json
import urllib.request

# This script runs in GitHub Actions, acts as the "Jules" FinOps Swarm, 
# and requires a GEMINI_API_KEY in GitHub Secrets.

API_KEY = os.environ.get("GEMINI_API_KEY")
LOG_FILE = "dashboard/data/engine_enrichment_log.md"

def ask_jules():
    if not API_KEY:
        return "ERROR: GEMINI_API_KEY missing. Please add it to GitHub Secrets."
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro-latest:generateContent?key={API_KEY}"
    
    prompt = """
    You are Jules, a continuous-improvement FinOps AI Swarm. Your goal is to make CloudThrift the #1 AWS FinOps engine.
    Act as a Red Team Hacker and Senior Cloud Architect. 
    1. Identify ONE highly obscure, deeply technical AWS cost leak or architectural inefficiency that tools like Trusted Advisor miss.
    2. Critique it ruthlessly. 
    3. Propose the detection logic for the CloudThrift engine.
    Format your response in Markdown with clear headers.
    """
    
    data = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode())
            return result['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return f"Failed to reach API: {e}"

if __name__ == "__main__":
    print("Starting Jules continuous improvement loop...")
    insight = ask_jules()
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    new_entry = f"\n\n---\n\n## Jules Automated Enrichment: {timestamp}\n\n{insight}\n"
    
    with open(LOG_FILE, "a") as f:
        f.write(new_entry)
    
    print("Enrichment logged successfully.")
