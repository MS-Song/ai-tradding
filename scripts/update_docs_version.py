import re
import os

def update_docs_version():
    try:
        with open("VERSION", "r") as f:
            version = f.read().strip()
    except Exception as e:
        print(f"Error reading VERSION file: {e}")
        return

    docs = ["gemini.md", "docs/USER_MANUAL.md"]
    
    # 정규식 패턴: [AI TRADING SYSTEM ver X.X.X] 또는 ver X.X.X 또는 vX.X.X
    patterns = [
        (r"ver \d+\.\d+\.\d+(\.\d+)?", f"ver {version}"),
        (r"v\d+\.\d+\.\d+(\.\d+)?", f"v{version}"),
        (r"\[AI TRADING SYSTEM ver \d+\.\d+\.\d+(\.\d+)?\]", f"[AI TRADING SYSTEM ver {version}]")
    ]

    for doc_path in docs:
        if not os.path.exists(doc_path):
            print(f"File not found: {doc_path}")
            continue
            
        with open(doc_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        new_content = content
        for pattern, replacement in patterns:
            new_content = re.sub(pattern, replacement, new_content)
            
        if new_content != content:
            with open(doc_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"Updated {doc_path} to version {version}")
        else:
            print(f"No changes needed for {doc_path}")

if __name__ == "__main__":
    update_docs_version()
