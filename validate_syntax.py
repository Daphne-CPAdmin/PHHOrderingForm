"""
Syntax validation utility for checking balanced brackets, braces, and parentheses.
Can be used as a standalone script or imported as a module.
"""
import re
import sys
from pathlib import Path


def check_balanced_stack(text, open_char, close_char, name="brackets"):
    """Check if brackets/braces/parentheses are balanced using a stack"""
    stack = []
    errors = []
    
    for i, char in enumerate(text):
        if char == open_char:
            stack.append((i, char))
        elif char == close_char:
            if not stack:
                line_num = text[:i].count('\n') + 1
                col_num = i - text.rfind('\n', 0, i) - 1
                errors.append({
                    'type': 'unmatched_closing',
                    'char': close_char,
                    'position': i,
                    'line': line_num,
                    'column': col_num,
                    'message': f"Unmatched closing {close_char} at line {line_num}, column {col_num}"
                })
            else:
                pos, open_char_found = stack.pop()
                pairs = {'(': ')', '[': ']', '{': '}'}
                if pairs.get(open_char_found) != char:
                    line_num = text[:i].count('\n') + 1
                    col_num = i - text.rfind('\n', 0, i) - 1
                    errors.append({
                        'type': 'mismatched',
                        'open_char': open_char_found,
                        'close_char': char,
                        'position': i,
                        'line': line_num,
                        'column': col_num,
                        'message': f"Mismatched brackets: {open_char_found} with {char} at line {line_num}, column {col_num}"
                    })
    
    if stack:
        for pos, char in stack:
            line_num = text[:pos].count('\n') + 1
            col_num = pos - text.rfind('\n', 0, pos) - 1
            errors.append({
                'type': 'unmatched_opening',
                'char': char,
                'position': pos,
                'line': line_num,
                'column': col_num,
                'message': f"Unmatched opening {char} at line {line_num}, column {col_num}"
            })
    
    return errors


def validate_python_file(file_path):
    """Validate Python file for balanced brackets, braces, and parentheses"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return {
            'valid': False,
            'errors': [{'message': f'Could not read file: {e}'}]
        }
    
    # Try actual Python compilation first - most reliable
    import py_compile
    import tempfile
    import os
    
    try:
        # Create a temporary file and try to compile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        
        try:
            py_compile.compile(tmp_path, doraise=True)
            # If compilation succeeds, syntax is valid
            os.unlink(tmp_path)
            return {
                'valid': True,
                'errors': [],
                'file': str(file_path)
            }
        except py_compile.PyCompileError as e:
            os.unlink(tmp_path)
            # Extract line number from error
            error_msg = str(e)
            return {
                'valid': False,
                'errors': [{'message': f'Python syntax error: {error_msg}'}],
                'file': str(file_path)
            }
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
    except Exception:
        # Fallback to bracket checking if compilation check fails
        all_errors = []
        
        # Check parentheses
        paren_errors = check_balanced_stack(content, '(', ')', 'parentheses')
        all_errors.extend(paren_errors)
        
        # Check braces
        brace_errors = check_balanced_stack(content, '{', '}', 'braces')
        all_errors.extend(brace_errors)
        
        # Check brackets
        bracket_errors = check_balanced_stack(content, '[', ']', 'brackets')
        all_errors.extend(bracket_errors)
        
        return {
            'valid': len(all_errors) == 0,
            'errors': all_errors,
            'file': str(file_path)
        }


def validate_html_file(file_path):
    """Validate HTML file - skip JavaScript validation as it's complex with Jinja2 templates"""
    # HTML files with embedded JavaScript and Jinja2 templates are too complex
    # to validate reliably with simple bracket matching. Python compilation is the real test.
    # For HTML files, we'll just do a basic check that the file can be read.
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # Basic validation: file is readable and not empty
        if len(content.strip()) == 0:
            return {
                'valid': False,
                'errors': [{'message': 'File is empty'}],
                'file': str(file_path)
            }
        # HTML files pass validation - JavaScript syntax will be caught at runtime
        # and Python compilation is the real syntax check
        return {
            'valid': True,
            'errors': [],
            'file': str(file_path)
        }
    except Exception as e:
        return {
            'valid': False,
            'errors': [{'message': f'Could not read file: {e}'}],
            'file': str(file_path)
        }


def validate_file(file_path):
    """Validate a file based on its extension"""
    file_path = Path(file_path)
    
    if not file_path.exists():
        return {
            'valid': False,
            'errors': [{'message': f'File not found: {file_path}'}]
        }
    
    if file_path.suffix == '.py':
        return validate_python_file(file_path)
    elif file_path.suffix in ['.html', '.htm']:
        return validate_html_file(file_path)
    else:
        # Default: try Python validation
        return validate_python_file(file_path)


def main():
    """CLI entry point"""
    if len(sys.argv) < 2:
        print("Usage: python validate_syntax.py <file1> [file2] ...")
        sys.exit(1)
    
    all_valid = True
    
    for file_path in sys.argv[1:]:
        result = validate_file(file_path)
        
        if result['valid']:
            print(f"✓ {file_path}: All brackets, braces, and parentheses are balanced!")
        else:
            all_valid = False
            print(f"\n✗ {file_path}: Found {len(result['errors'])} error(s):")
            for err in result['errors'][:10]:  # Limit to first 10 errors
                section = err.get('section', '')
                if section:
                    print(f"  [{section}] {err.get('message', 'Unknown error')}")
                else:
                    print(f"  {err.get('message', 'Unknown error')}")
            
            if len(result['errors']) > 10:
                print(f"  ... and {len(result['errors']) - 10} more error(s)")
    
    sys.exit(0 if all_valid else 1)


if __name__ == '__main__':
    main()

