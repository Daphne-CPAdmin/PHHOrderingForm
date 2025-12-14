#!/usr/bin/env python3
"""
Local testing script - validates setup and runs the Flask app
"""
import os
import sys
from pathlib import Path

def check_setup():
    """Check if everything is set up correctly"""
    print("🔍 Checking local setup...\n")
    
    issues = []
    
    # Check Python version
    if sys.version_info < (3, 8):
        issues.append(f"❌ Python 3.8+ required. Found: {sys.version}")
    else:
        print(f"✓ Python version: {sys.version.split()[0]}")
    
    # Check virtual environment
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        print("✓ Virtual environment is active")
    else:
        print("⚠️  Virtual environment not detected (recommended but not required)")
    
    # Check .env file
    env_file = Path('.env')
    if env_file.exists():
        print("✓ .env file exists")
        
        # Check critical variables
        from dotenv import load_dotenv
        load_dotenv()
        
        required_vars = ['GOOGLE_SHEETS_ID', 'ADMIN_PASSWORD']
        for var in required_vars:
            if os.getenv(var):
                print(f"✓ {var} is set")
            else:
                issues.append(f"❌ {var} is missing in .env")
    else:
        issues.append("❌ .env file not found - create one with required variables")
    
    # Check requirements
    req_file = Path('requirements.txt')
    if req_file.exists():
        print("✓ requirements.txt exists")
    else:
        issues.append("❌ requirements.txt not found")
    
    # Check if dependencies are installed
    try:
        import flask
        print(f"✓ Flask installed: {flask.__version__}")
    except ImportError:
        issues.append("❌ Flask not installed")
        print("   💡 Run: pip install -r requirements.txt")
    
    try:
        import gspread
        print("✓ gspread installed")
    except ImportError:
        issues.append("❌ gspread not installed")
        print("   💡 Run: pip install -r requirements.txt")
    
    try:
        from dotenv import load_dotenv
        print("✓ python-dotenv installed")
    except ImportError:
        issues.append("❌ python-dotenv not installed")
        print("   💡 Run: pip install -r requirements.txt")
    
    # Check syntax
    print("\n🔍 Validating syntax...")
    try:
        from pre_update_validation import validate_project_files
        result = validate_project_files()
        if result == 0:
            print("✓ All files pass syntax validation")
        else:
            issues.append("⚠️  Syntax validation found issues - check output above")
    except Exception as e:
        issues.append(f"⚠️  Could not run syntax validation: {e}")
    
    print("\n" + "="*60)
    if issues:
        print("❌ Setup Issues Found:\n")
        for issue in issues:
            print(f"  {issue}")
        print("\n📋 Quick Setup Steps:")
        print("  1. Create virtual environment: python3 -m venv venv")
        print("  2. Activate it: source venv/bin/activate (Mac/Linux) or venv\\Scripts\\activate (Windows)")
        print("  3. Install dependencies: pip install -r requirements.txt")
        print("  4. Create .env file with required variables (see LOCAL_TESTING.md)")
        print("  5. Run this script again: python3 test_local.py")
        return False
    else:
        print("✅ Setup looks good! Ready to test locally.")
        return True

def run_app():
    """Run the Flask app"""
    print("\n🚀 Starting Flask app...")
    print("📍 App will be available at: http://localhost:5000")
    print("📍 Admin panel: http://localhost:5000/admin")
    print("\n💡 Press Ctrl+C to stop the server\n")
    
    # Import and run app
    from app import app
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'true').lower() == 'true'
    app.run(debug=debug, host='127.0.0.1', port=port)

if __name__ == '__main__':
    if check_setup():
        print("\n" + "="*60)
        run_app()
    else:
        sys.exit(1)

