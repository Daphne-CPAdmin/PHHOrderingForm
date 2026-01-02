# Tab-Specific Lock Message Fix

## 🐛 Issue
When PepHaul Entry-02 was locked in the Admin Panel, the customer view was still showing:
- ❌ Order Statistics section (should be hidden)
- ❌ No lock message banner (should be visible)
- ❌ No Order Timeline (should be visible)

The system has **tab-specific locking** (each PepHaul Entry can be locked independently), but the customer panel wasn't respecting the per-tab lock status.

---

## ✅ Root Causes Found & Fixed

### **1. Template Variable Mismatch**
**Problem:** Template was looking for `order_form_lock_message` but backend was passing `lock_message`

**Location:** `templates/index.html` line 1881

**Before:**
```jinja2
{% if order_form_lock_message %}
    {{ order_form_lock_message|safe }}
```

**After:**
```jinja2
{% if lock_message %}
    {{ lock_message|safe }}
```

**Why this matters:** The backend (app.py line 3099) passes `lock_message=tab_lock_status['message']`, so the template must use the same variable name.

---

### **2. JavaScript Selector Not Working**
**Problem:** JavaScript was using `document.querySelector('.stats-banner.supplier-stats[data-supplier="{{ tab_supplier }}"]')`

**Issue:** Jinja2 variables (`{{ tab_supplier }}`) inside JavaScript strings don't get interpolated correctly.

**Before:**
```javascript
const statsSection = document.querySelector('.stats-banner.supplier-stats[data-supplier="{{ tab_supplier }}"]');
```

**After:**
```javascript
const statsSection = document.querySelector('.stats-banner.supplier-stats');
```

**Why this matters:** Using just the class selector is more reliable and matches the element regardless of supplier.

---

### **3. Added Debug Logging**
Added console logging to help diagnose visibility issues:

```javascript
console.log('[DOMContentLoaded] Order form locked status:', orderFormLocked);
console.log('[DOMContentLoaded] Stats section found:', statsSection);
console.log('[DOMContentLoaded] Stats section hidden');
console.log('[DOMContentLoaded] Lock banner found:', lockBanner);
console.log('[DOMContentLoaded] Lock banner shown');
console.log('[DOMContentLoaded] Timeline section found:', timelineSection);
console.log('[DOMContentLoaded] Timeline section shown');
```

These logs will appear in the browser console and help verify that the visibility logic is working.

---

## 🔧 How Tab-Specific Locking Works

### **Backend (app.py)**
1. **Tab lock status stored in Google Sheets:**
   - Sheet: "Settings"
   - Column A: "Tab Lock Status"
   - Column B: Tab name (e.g., "PepHaul Entry-02")
   - Column C: "Yes" or "No"
   - Column D: Custom lock message

2. **Functions:**
   - `get_tab_lock_status(tab_name)` - Gets lock status for specific tab
   - `set_tab_lock_status(tab_name, is_locked, message)` - Sets lock status for specific tab

3. **Route handler (`index()`):**
   ```python
   # Get lock status for current tab
   tab_lock_status = get_tab_lock_status(current_tab)
   
   return render_template('index.html',
                         order_form_locked=tab_lock_status['is_locked'],
                         lock_message=tab_lock_status['message'],
                         ...)
   ```

### **Frontend (templates/index.html)**
1. **Server-side rendering (Jinja2):**
   - `{% if not order_form_locked %}` - Hides Order Statistics section
   - `{% if order_form_locked %}` - Shows lock banner and timeline

2. **Client-side JavaScript:**
   - DOMContentLoaded event handler manages visibility
   - Hides/shows sections based on `orderFormLocked` variable
   - Loads timeline and customer summary when locked

---

## 📊 Before vs After

### **Before (BROKEN):**
When PepHaul Entry-02 is locked:
- ❌ Order Statistics still showing
- ❌ Lock message not visible
- ❌ Timeline hidden
- ❌ Template variable mismatch
- ❌ JavaScript selector failing

### **After (FIXED):**
When PepHaul Entry-02 is locked:
- ✅ Order Statistics **HIDDEN**
- ✅ Lock message **VISIBLE** (red banner with custom message)
- ✅ Timeline **VISIBLE**
- ✅ Template variables match backend
- ✅ JavaScript selector working reliably

---

## 🧪 Testing Instructions

### **Test Scenario:**

1. **In Admin Panel:**
   - Go to "Order Form Status" section
   - Find "PepHaul Entry-02" (or any tab)
   - Click "🔒 Lock" button
   - Set custom lock message: "Orders for PepHaul Entry-02 are currently closed. Thank you for your patience!"
   - Save

2. **In Customer View:**
   - Navigate to `/` (customer order form)
   - **Expected results:**
     - ✅ Lock message banner shows at top (red, with your custom message)
     - ✅ Order Timeline shows below lock message
     - ✅ Order Statistics section is HIDDEN
     - ✅ Customers can view/pay existing orders
     - ✅ Customers CANNOT submit new orders

3. **In Browser Console (F12):**
   - Check for these log messages:
     ```
     [DOMContentLoaded] Order form locked status: true
     [DOMContentLoaded] Stats section found: <div class="stats-banner supplier-stats">
     [DOMContentLoaded] Stats section hidden
     [DOMContentLoaded] Lock banner found: <div id="locked-banner">
     [DOMContentLoaded] Lock banner shown
     [DOMContentLoaded] Timeline section found: <div id="timeline-section">
     [DOMContentLoaded] Timeline section shown
     ```

4. **Test Unlocking:**
   - In Admin Panel, click "Unlock Form" for PepHaul Entry-02
   - Refresh customer view
   - **Expected results:**
     - ✅ Lock message hidden
     - ✅ Timeline hidden
     - ✅ Order Statistics section VISIBLE
     - ✅ Full ordering functionality enabled

---

## 🔍 Debugging Tips

If lock message still not showing:

1. **Check Browser Console:**
   - Open DevTools (F12)
   - Look for the console logs
   - Verify `orderFormLocked` is `true`

2. **Check Google Sheets:**
   - Open "Settings" sheet
   - Look for row with:
     - Column A: "Tab Lock Status"
     - Column B: "PepHaul Entry-02"
     - Column C: "Yes"
     - Column D: Your custom message

3. **Check Backend:**
   - Verify `get_tab_lock_status('PepHaul Entry-02')` returns `{'is_locked': True, 'message': '...'}`

4. **Clear Cache:**
   - The lock status is cached for 10 minutes
   - Wait 10 minutes or restart the Flask server to clear cache

---

## 🚀 Deployment Status

✅ **Committed:** `e405fc7`
✅ **Pushed to GitHub:** `main` branch

---

## 📝 Technical Notes

**Why Jinja2 variables don't work in JavaScript:**

```javascript
// ❌ WRONG - Jinja2 variable inside JS string literal
const selector = '.stats[data-supplier="{{ tab_supplier }}"]';
// Result: '.stats[data-supplier="{{ tab_supplier }}"]' (literal string)

// ✅ CORRECT - Jinja2 variable directly in JS
const supplier = "{{ tab_supplier }}";
const selector = `.stats[data-supplier="${supplier}"]`;
// Result: '.stats[data-supplier="YIWU"]' (interpolated)
```

In our fix, we avoided this issue by using a class-based selector that doesn't depend on the supplier attribute.

---

## 🎯 Summary

The customer panel now correctly:
- Shows lock message when tab is locked
- Hides Order Statistics when tab is locked
- Shows Order Timeline when tab is locked
- Respects per-tab lock status (independent locking for each PepHaul Entry)

