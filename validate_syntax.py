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
    """Validate HTML file for balanced brackets, braces, and parentheses in JavaScript/Jinja sections"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return {
            'valid': False,
            'errors': [{'message': f'Could not read file: {e}'}]
        }
    
    all_errors = []
    
    # Extract JavaScript sections (between <script> tags)
    script_pattern = r'<script[^>]*>(.*?)</script>'
    scripts = re.findall(script_pattern, content, re.DOTALL)
    
    for idx, script_content in enumerate(scripts):
        # Check JavaScript code
        paren_errors = check_balanced_stack(script_content, '(', ')', 'parentheses')
        brace_errors = check_balanced_stack(script_content, '{', '}', 'braces')
        bracket_errors = check_balanced_stack(script_content, '[', ']', 'brackets')
        
        for err in paren_errors + brace_errors + bracket_errors:
            err['section'] = f'JavaScript section {idx + 1}'
            all_errors.append(err)
    
    # Check Jinja2 template expressions {{ ... }}
    jinja_pattern = r'\{\{([^}]*)\}\}'
    jinja_matches = re.finditer(jinja_pattern, content)
    
    for match in jinja_matches:
        expr = match.group(1)
        paren_errors = check_balanced_stack(expr, '(', ')', 'parentheses')
        bracket_errors = check_balanced_stack(expr, '[', ']', 'brackets')
        
        for err in paren_errors + bracket_errors:
            line_num = content[:match.start()].count('\n') + 1
            err['section'] = f'Jinja2 template at line {line_num}'
            all_errors.append(err)
    
    # Check JavaScript template literals ${...} - handle nested braces properly
    # The regex [^}]* stops at first }, but we need to handle nested {} in object literals
    # So we'll use a more sophisticated approach: find ${ and then match balanced braces
    i = 0
    while i < len(content):
        if content[i:i+2] == '${':
            # Find the matching closing brace, handling nested braces
            depth = 0
            j = i + 2
            start_pos = j
            
            while j < len(content):
                if content[j] == '{':
                    depth += 1
                elif content[j] == '}':
                    if depth == 0:
                        # Found the closing brace for this template literal
                        expr = content[start_pos:j]
                        line_num = content[:i].count('\n') + 1
                        
                        # Check parentheses and brackets (braces are part of the template literal syntax)
                        paren_errors = check_balanced_stack(expr, '(', ')', 'parentheses')
                        bracket_errors = check_balanced_stack(expr, '[', ']', 'brackets')
                        
                        for err in paren_errors + bracket_errors:
                            err['section'] = f'JavaScript template literal at line {line_num}'
                            all_errors.append(err)
                        
                        i = j + 1
                        break
                    else:
                        depth -= 1
                j += 1
            else:
                # No closing brace found - this is an error, but skip for now
                i += 1
        else:
            i += 1
    
    return {
        'valid': len(all_errors) == 0,
        'errors': all_errors,
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

