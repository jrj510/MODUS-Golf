install the same packages in terminal with:

Step 1 copy the following in separate commands into a terminal:

python -m venv C:\venvs\modus-golf

C:\venvs\modus-golf\Scripts\Activate.ps1

python -m pip install --upgrade pip setuptools wheel

pip install -r requirements-dev.txt

Step 2:
make sure your .gitignore file looks like this:
# Virtual environment
venv/

# Python cache
__pycache__/
*.pyc

# VS Code
.vscode/

# OS files
.DS_Store
Thumbs.db

*.pt
----------------------------------------------------------------------------------------------
