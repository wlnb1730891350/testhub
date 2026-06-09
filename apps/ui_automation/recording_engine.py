"""
鏅鸿兘褰曞埗寮曟搸 - 鍩轰簬 Playwright 鐨勬祻瑙堝櫒鎿嶄綔褰曞埗
"""
import json
import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
from typing import Optional
from django.db import transaction

logger = logging.getLogger(__name__)

# 褰曞埗鎿嶄綔绫诲瀷瀹氫箟
_active_sessions = {}
_session_lock = threading.Lock()

# 褰曞埗寮曟搸妯″潡
RECORDER_SCRIPT = """
(function() {
    try {
    if (window.__testhub_recorder_injected) { console.log('[TestHub] Already injected, skip'); return; }
    window.__testhub_recorder_injected = true;
    window.__testhub_actions = [];
    console.log('[TestHub] Recorder starting injection...');

    var SESSION_ID = %%SESSION_ID_JSON%%;
    var API_URL = 'http://127.0.0.1:8001/api/ui-automation/recording/actions/';
    var AUTH_TOKEN = %%AUTH_TOKEN_JSON%%;

    function getCssSelector(el) {
        if (!(el instanceof Element)) return '';
        var parts = [];
        var current = el;
        while (current && current.nodeType === Node.ELEMENT_NODE) {
            var selector = current.nodeName.toLowerCase();
            if (current.id) {
                parts.unshift('#' + CSS.escape(current.id));
                break;
            }
            if (current === document.body) { parts.unshift('body'); break; }
            var parent = current.parentElement;
            if (parent) {
                var siblings = Array.from(parent.children).filter(
                    function(c) { return c.nodeName === current.nodeName; }
                );
                if (siblings.length > 1) {
                    var idx = siblings.indexOf(current) + 1;
                    selector += ':nth-of-type(' + idx + ')';
                }
            }
            parts.unshift(selector);
            current = current.parentElement;
        }
        return parts.join(' > ');
    }

    function getXPath(el) {
        if (!(el instanceof Element)) return '';
        var parts = [];
        var current = el;
        while (current && current.nodeType === Node.ELEMENT_NODE) {
            if (current.id) {
                parts.unshift('id("' + current.id + '")');
                break;
            }
            var idx = 1;
            var sib = current.previousSibling;
            while (sib) {
                if (sib.nodeType === 1 && sib.nodeName === current.nodeName) idx++;
                sib = sib.previousSibling;
            }
            parts.unshift(current.nodeName.toLowerCase() + '[' + idx + ']');
            current = current.parentNode;
        }
        return '/' + parts.join('/');
    }

    function getElementLabel(el) {
        if (!(el instanceof Element)) return '';
        var ariaLabel = (el.getAttribute('aria-label') || '').trim();
        if (ariaLabel) return ariaLabel;
        var placeholder = (el.getAttribute('placeholder') || '').trim();
        if (placeholder) return placeholder;
        var title = (el.getAttribute('title') || '').trim();
        if (title) return title;
        var value = (el.value || '').trim();
        if (value && ['button', 'submit'].indexOf((el.getAttribute('type') || '').toLowerCase()) >= 0) return value;
        var directText = Array.from(el.childNodes)
            .filter(function(n) { return n.nodeType === 3; })
            .map(function(n) { return (n.textContent || '').trim(); })
            .join(' ')
            .trim();
        if (directText) return directText.substring(0, 80);
        var text = (el.textContent || '').trim();
        if (text) return text.substring(0, 80);
        return '';
    }

    function isUsefulTarget(el) {
        if (!(el instanceof Element)) return false;
        var tag = (el.tagName || '').toLowerCase();
        if (['button', 'a', 'input', 'textarea', 'select', 'option', 'label'].indexOf(tag) >= 0) return true;
        var role = (el.getAttribute('role') || '').toLowerCase();
        if (['button', 'link', 'tab', 'menuitem', 'option', 'checkbox', 'radio', 'switch', 'textbox'].indexOf(role) >= 0) return true;
        if (el.hasAttribute('onclick')) return true;
        if (el.hasAttribute('data-testid') || el.hasAttribute('data-cy') || el.hasAttribute('data-qa')) return true;
        if (el.hasAttribute('placeholder') || el.hasAttribute('aria-label') || el.hasAttribute('name')) return true;
        var className = typeof el.className === 'string' ? el.className : '';
        if (/(button|btn|link|input|select|option|checkbox|radio|switch|tab)/i.test(className)) return true;
        return false;
    }

    function isGenericContainer(el) {
        if (!(el instanceof Element)) return false;
        var tag = (el.tagName || '').toLowerCase();
        var id = (el.id || '').toLowerCase();
        var className = typeof el.className === 'string' ? el.className.toLowerCase() : '';
        if (['html', 'body', 'main', 'section'].indexOf(tag) >= 0) return true;
        if (/(container|wrapper|content|layout|main)/.test(id)) return true;
        if (/(container|wrapper|content|layout|main)/.test(className) && !isUsefulTarget(el)) return true;
        return false;
    }

    function getTextLength(el) {
        return getElementLabel(el).length;
    }

    function scoreTargetCandidate(el, preferredTagNames) {
        if (!(el instanceof Element)) return -9999;
        var tag = (el.tagName || '').toLowerCase();
        var score = 0;
        if (preferredTagNames && preferredTagNames.indexOf(tag) >= 0) score += 80;
        if (isUsefulTarget(el)) score += 50;
        if (el.id) score += 10;
        if (el.hasAttribute('data-testid') || el.hasAttribute('data-cy') || el.hasAttribute('data-qa')) score += 40;
        if (el.hasAttribute('placeholder') || el.hasAttribute('aria-label') || el.hasAttribute('name')) score += 25;
        if (['button', 'a', 'input', 'textarea', 'select', 'label'].indexOf(tag) >= 0) score += 20;
        if (isGenericContainer(el)) score -= 80;

        var textLength = getTextLength(el);
        if (textLength > 0 && textLength <= 40) score += 20;
        if (textLength > 80) score -= 40;

        var rect;
        try {
            rect = el.getBoundingClientRect();
            var area = rect.width * rect.height;
            if (area > 0 && area < 200000) score += 15;
            if (area >= 200000) score -= 30;
        } catch (e) {}

        return score;
    }

    function findActionTarget(el, preferredTagNames) {
        if (!(el instanceof Element)) return el;
        var best = el;
        var bestScore = scoreTargetCandidate(el, preferredTagNames);
        var current = el.parentElement;
        var depth = 0;
        while (current && current !== document.body && depth < 8) {
            var currentScore = scoreTargetCandidate(current, preferredTagNames) - depth * 3;
            if (currentScore > bestScore) {
                best = current;
                bestScore = currentScore;
            }
            current = current.parentElement;
            depth += 1;
        }
        return best || el;
    }

    function getLocator(el) {
        if (!(el instanceof Element)) return { strategy: 'css', value: '', description: '' };
        var testAttrs = ['data-testid', 'data-cy', 'data-qa'];
        for (var ai = 0; ai < testAttrs.length; ai++) {
            var attr = testAttrs[ai];
            var val = el.getAttribute(attr);
            if (val) return { strategy: 'css', value: '[' + attr + '="' + CSS.escape(val) + '"]', description: attr + '=' + val };
        }
        var ariaLabel = el.getAttribute('aria-label');
        if (ariaLabel) return { strategy: 'css', value: '[aria-label="' + CSS.escape(ariaLabel) + '"]', description: 'aria-label=' + ariaLabel };
        if (el.id) return { strategy: 'id', value: el.id, description: 'id=' + el.id };
        var name = el.getAttribute('name');
        if (name) return { strategy: 'css', value: '[name="' + CSS.escape(name) + '"]', description: 'name=' + name };
        var placeholder = el.getAttribute('placeholder');
        if (placeholder) return { strategy: 'css', value: '[placeholder="' + CSS.escape(placeholder) + '"]', description: 'placeholder=' + placeholder };
        var role = el.getAttribute('role');
        if (role && getElementLabel(el)) {
            return { strategy: 'css', value: '[role="' + CSS.escape(role) + '"]', description: 'role=' + role + ' ' + getElementLabel(el) };
        }
        var tag = el.tagName.toLowerCase();
        var text = getElementLabel(el).substring(0, 50);
        if (text && text.length < 50 && ['a','button','label','span','td','th','li'].indexOf(tag) >= 0) {
            return { strategy: 'text', value: text, description: 'text=' + text };
        }
        var css = getCssSelector(el);
        return { strategy: 'css', value: css, description: css };
    }

    function getElementInfo(el) {
        if (!(el instanceof Element)) {
            return { tag: '', type: '', text: '', id: '', name: '' };
        }
        var tag = el.tagName.toLowerCase();
        var type = el.getAttribute('type') || '';
        var text = getElementLabel(el);
        var placeholder = el.getAttribute('placeholder') || '';
        return { tag: tag, type: type, text: text, id: el.id || '', name: el.getAttribute('name') || '', placeholder: placeholder };
    }

    var _buffer = [];
    var _flushTimer = null;

    function sendAction(action) {
        console.log('[TestHub] Action captured:', action.action_type, action.locator_value, action.element_text);
        window.__testhub_actions.push(action);
        // Deliver immediately via expose_function (real-time)
        if (typeof window.__testhub_send_actions === 'function') {
            try {
                window.__testhub_send_actions(JSON.stringify([action]));
                console.log('[TestHub] Sent via expose_function');
                return;
            } catch(ex) {
                console.log('[TestHub] expose_function failed: ' + ex.message);
            }
        }
        _buffer.push(action);
        if (_flushTimer) clearTimeout(_flushTimer);
        _flushTimer = setTimeout(flush, 500);
    }

    function flush() {
        if (_buffer.length === 0) return;
        var toSend = _buffer.splice(0);
        console.log('[TestHub] Flushing ' + toSend.length + ' actions');
        // Try direct Python call first (bypasses CORS)
        if (typeof window.__testhub_send_actions === 'function') {
            try {
                window.__testhub_send_actions(JSON.stringify(toSend));
                console.log('[TestHub] Sent via expose_function');
                return;
            } catch(ex) {
                console.log('[TestHub] expose_function failed, falling back to fetch: ' + ex.message);
            }
        }
        // Fallback: fetch via route interception
        var body = JSON.stringify({ session_id: SESSION_ID, actions: toSend });
        try {
            fetch(API_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + AUTH_TOKEN },
                body: body
            }).then(function(r) {
                console.log('[TestHub] API response: ' + r.status);
                return r.text();
            }).then(function(t) {
                console.log('[TestHub] API body: ' + t.substring(0, 200));
            }).catch(function(e) {
                console.error('[TestHub] Fetch error: ' + e.message);
            });
        } catch(e) {
            console.error('[TestHub] Fetch throw: ' + e.message);
        }
    }

    var _pendingInput = null;
    var _inputTimer = null;

    function flushPendingInput() {
        if (_pendingInput) {
            if (_inputTimer) { clearTimeout(_inputTimer); _inputTimer = null; }
            sendAction(_pendingInput);
            _pendingInput = null;
        }
    }

    function normalizeKeyName(key) {
        if (!key) return '';
        if (key === ' ') return 'Space';
        if (key === 'Control') return 'Control';
        if (key === 'Meta') return 'Meta';
        if (key === 'Alt') return 'Alt';
        if (key === 'Shift') return 'Shift';
        return key.length === 1 ? key.toUpperCase() : key;
    }

    function buildShortcut(e) {
        var parts = [];
        if (e.ctrlKey && e.key !== 'Control') parts.push('Control');
        if (e.metaKey && e.key !== 'Meta') parts.push('Meta');
        if (e.altKey && e.key !== 'Alt') parts.push('Alt');
        if (e.shiftKey && e.key !== 'Shift') parts.push('Shift');
        parts.push(normalizeKeyName(e.key));
        return parts.filter(Boolean).join('+');
    }

    document.addEventListener('click', function(e) {
        flushPendingInput();
        var rawTarget = e.target instanceof Element ? e.target : document.elementFromPoint(e.clientX, e.clientY);
        var el = findActionTarget(rawTarget, ['button', 'a', 'input', 'textarea', 'select', 'label']);
        if (el.id === '__testhub_record_indicator') return;
        var locator = getLocator(el);
        var info = getElementInfo(el);
        sendAction({ action_type: 'click', locator_strategy: locator.strategy, locator_value: locator.value, locator_description: locator.description, element_tag: info.tag, element_text: info.text, element_type: info.type, page_url: location.href, page_title: document.title, click_x: e.clientX, click_y: e.clientY, timestamp: Date.now() });
    }, true);

    document.addEventListener('input', function(e) {
        var el = findActionTarget(e.target, ['input', 'textarea', 'select']);
        var tag = el.tagName.toLowerCase();
        if (['input', 'textarea', 'select'].indexOf(tag) < 0) return;
        if (_inputTimer) clearTimeout(_inputTimer);
        var locator = getLocator(el);
        var info = getElementInfo(el);
        _pendingInput = { action_type: 'fill', locator_strategy: locator.strategy, locator_value: locator.value, locator_description: locator.description, element_tag: info.tag, element_text: info.text, input_value: el.value, page_url: location.href, page_title: document.title, timestamp: Date.now() };
        _inputTimer = setTimeout(function() { if (_pendingInput) { sendAction(_pendingInput); _pendingInput = null; } }, 800);
    }, true);

    document.addEventListener('change', function(e) {
        var el = findActionTarget(e.target, ['select', 'input', 'textarea']);
        if (el.tagName.toLowerCase() === 'select') {
            flushPendingInput();
            var locator = getLocator(el);
            var info = getElementInfo(el);
            sendAction({ action_type: 'fill', locator_strategy: locator.strategy, locator_value: locator.value, locator_description: locator.description, element_tag: info.tag, element_text: info.text, input_value: el.value, page_url: location.href, page_title: document.title, timestamp: Date.now() });
        }
    }, true);

    document.addEventListener('keydown', function(e) {
        var key = normalizeKeyName(e.key);
        var hasModifier = e.ctrlKey || e.metaKey || e.altKey;
        var specialKeys = ['Enter', 'Tab', 'Escape', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Backspace', 'Delete', 'Home', 'End', 'PageUp', 'PageDown'];
        if (!hasModifier && specialKeys.indexOf(key) < 0) return;
        if (key === 'Shift' || key === 'Control' || key === 'Alt' || key === 'Meta') return;

        flushPendingInput();
        var el = e.target instanceof Element ? e.target : document.activeElement;
        el = findActionTarget(el, ['input', 'textarea', 'select', 'button', 'a']);
        if (!(el instanceof Element)) return;
        if (el.id === '__testhub_record_indicator') return;

        var locator = getLocator(el);
        var info = getElementInfo(el);
        sendAction({
            action_type: 'press',
            locator_strategy: locator.strategy,
            locator_value: locator.value,
            locator_description: locator.description,
            element_tag: info.tag,
            element_text: info.text,
            element_type: info.type,
            input_value: buildShortcut(e),
            page_url: location.href,
            page_title: document.title,
            timestamp: Date.now()
        });
    }, true);

    document.addEventListener('submit', function(e) { flushPendingInput(); }, true);

    function _addIndicator() {
        if (!document.body) return;
        var indicator = document.createElement('div');
        indicator.id = '__testhub_record_indicator';
        indicator.innerHTML = '\u25CF REC';
        Object.assign(indicator.style, { position: 'fixed', top: '10px', right: '10px', zIndex: '2147483647', background: '#e53935', color: 'white', padding: '6px 14px', borderRadius: '20px', fontSize: '13px', fontWeight: 'bold', fontFamily: 'system-ui, sans-serif', boxShadow: '0 2px 8px rgba(0,0,0,0.3)', cursor: 'default', userSelect: 'none', animation: '__testhub_pulse 1.5s infinite' });
        var style = document.createElement('style');
        style.textContent = '@keyframes __testhub_pulse { 0%,100%{opacity:1} 50%{opacity:0.6} }';
        document.head.appendChild(style);
        document.body.appendChild(indicator);
    }
    if (document.body) { _addIndicator(); } else { document.addEventListener('DOMContentLoaded', _addIndicator); }

    console.log('[TestHub] Recorder injected OK - ' + location.href);
    setInterval(function(){ console.log('[TestHub] Heartbeat - actions: ' + window.__testhub_actions.length); }, 5000);
    } catch(e) { console.error('[TestHub] Recorder FAILED:', e.message, e.stack); }
})();
"""


class RecordingEngine:
    """Playwright browser recording engine."""

    @staticmethod
    def get_locator_strategy_id(strategy_name):
        from .models import LocatorStrategy
        mapping = {"css": 1, "xpath": 2, "id": 3, "text": 4}
        if strategy_name in mapping:
            return mapping[strategy_name]
        try:
            return LocatorStrategy.objects.get(name=strategy_name).id
        except Exception:
            return 1

    @staticmethod
    def infer_element_type(tag, input_type="", text=""):
        tag = tag.lower()
        if tag in ("input", "textarea"):
            return "INPUT"
        if tag == "select":
            return "DROPDOWN"
        if tag == "button" or (tag == "input" and input_type == "button"):
            return "BUTTON"
        if tag == "a":
            return "LINK"
        if tag == "img":
            return "IMAGE"
        if tag == "table":
            return "TABLE"
        if tag in ("div", "form", "section"):
            return "CONTAINER"
        return "TEXT"

    @staticmethod
    def generate_element_name(action):
        tag = action.get("element_tag", "element")
        text = action.get("element_text", "")
        desc = action.get("locator_description", "")
        locator = action.get("locator_value", "")
        if text and len(text) < 30:
            return f"{tag}[{text}]"
        if desc and len(desc) < 50:
            return f"{tag}[{desc}]"
        if locator and len(locator) < 80:
            return f"{tag}[{locator}]"
        return f"{tag}_{action.get('timestamp', '')}"

    @staticmethod
    def generate_step_description(action):
        action_type = action.get("action_type", "click")
        text = action.get("element_text", "").strip()[:30]
        input_val = action.get("input_value", "")
        desc = action.get("locator_description", "")
        locator = action.get("locator_value", "")
        if action_type == "click":
            if text:
                return f"Click [{text}]"
            if desc:
                return f"Click {desc}"
            if locator:
                return f"Click {locator}"
            return "Click unknown element"
        elif action_type == "fill":
            if text:
                return f"Fill [{text}] value \"{input_val}\""
            if desc:
                return f"Fill {desc} value \"{input_val}\""
            if locator:
                return f"Fill {locator} value \"{input_val}\""
            return f"Fill \"{input_val}\""
        elif action_type == "press":
            if text:
                return f"Press [{text}] key \"{input_val}\""
            if desc:
                return f"Press {desc} key \"{input_val}\""
            if locator:
                return f"Press {locator} key \"{input_val}\""
            return f"Press key \"{input_val}\""
        return action_type

    @classmethod
    def start_recording(cls, session_id, start_url, project_id,
                        browser_type="chromium", headless=False, user=None, auth_token=""):
        from .models import RecordingSession, UiProject

        with _session_lock:
            if session_id in _active_sessions:
                return {"success": False, "error": "鍚姩褰曞埗澶辫触"}
            try:
                project = UiProject.objects.get(id=project_id)
            except UiProject.DoesNotExist:
                return {"success": False, "error": "鍋滄褰曞埗澶辫触"}

            session = RecordingSession.objects.create(
                session_id=session_id,
                project=project,
                start_url=start_url,
                status="starting",
                browser=browser_type,
                headless=headless,
                created_by=user,
            )
            _active_sessions[session_id] = {
                "session": session,
                "actions": [],
                "stop_event": threading.Event(),
                "thread": None,
                "error": None,
                "browser_closed": False,
            }

        thread = threading.Thread(
            target=cls._run_recording,
            args=(session_id, start_url, browser_type, headless, auth_token),
            daemon=True,
        )
        _active_sessions[session_id]["thread"] = thread
        thread.start()
        return {"success": True, "session_id": session_id}

    @classmethod
    def _run_recording(cls, session_id, start_url, browser_type, headless, auth_token=""):
        from .models import RecordingSession

        def update_status(status, error=""):
            def _do_update():
                try:
                    s = RecordingSession.objects.get(session_id=session_id)
                    s.status = status
                    if error:
                        s.error_message = error
                    s.save(update_fields=["status", "error_message", "updated_at"])
                except Exception as e:
                    logger.error(f"褰曞埗鐘舵€佹鏌ュけ璐? {e}")
            threading.Thread(target=_do_update, daemon=True).start()

        pw = None
        browser = None
        context = None

        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            launcher = {"chromium": pw.chromium, "firefox": pw.firefox, "webkit": pw.webkit}.get(browser_type, pw.chromium)
            # Launch Chrome directly (no profile copy needed)
            context = None
            browser = None

            # Try Chrome channel first (uses installed Chrome)
            try:
                browser = launcher.launch(
                    headless=headless,
                    channel="chrome",
                    args=["--ignore-certificate-errors", "--disable-web-security"],
                )
                context = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    ignore_https_errors=True,
                )
                page = context.new_page()
                logger.info("[Recording] Chrome launched successfully")
            except Exception as chrome_err:
                logger.warning("[Recording] Chrome launch failed: %s, falling back to Chromium", chrome_err)
                browser = launcher.launch(headless=headless)
                context = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    ignore_https_errors=True,
                )
                page = context.new_page()
                logger.info("[Recording] Bundled Chromium launched")


            # Intercept fetch calls from recorded pages to bypass CORS/mixed-content
            def handle_recording_route(route):
                """Forward recording actions fetch to Django API directly."""
                try:
                    import urllib.request
                    req_body = route.request.post_data
                    if req_body:
                        api_req = urllib.request.Request(
                            "http://127.0.0.1:8001/api/ui-automation/recording/actions/",
                            data=req_body.encode("utf-8") if isinstance(req_body, str) else req_body,
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        resp = urllib.request.urlopen(api_req)
                        body = resp.read().decode()
                        route.fulfill(
                            status=resp.status,
                            headers={"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
                            body=body,
                        )
                    else:
                        route.continue_()
                except Exception as e:
                    logger.warning("[Recording] Route handler error: %s", e)
                    route.abort()

            context.route("**/api/ui-automation/recording/actions/", handle_recording_route)


            # NOTE: Actions are now captured via Python-side polling loop (more reliable)
            # The polling loop reads window.__testhub_actions every 1 second

            def inject_recorder(p):
                """Inject recorder script using CDP primary, chunked fallback."""
                try:
                    # Always attempt injection - JS-side check handles deduplication
                    safe_session_id = json.dumps(str(session_id))
                    safe_token = json.dumps(str(auth_token or ""))
                    script_with_id = RECORDER_SCRIPT.replace("%%SESSION_ID_JSON%%", safe_session_id).replace("%%AUTH_TOKEN_JSON%%", safe_token)
                    logger.info("[Recording] Injecting script (%d chars) into %s", len(script_with_id), p.url)

                    injected = False

                    # Method 1: CDP Runtime.evaluate (bypasses Playwright expression parser)
                    if not injected:
                        try:
                            cdp = context.new_cdp_session(p)
                            result = cdp.send("Runtime.evaluate", {
                                "expression": script_with_id,
                                "awaitPromise": False,
                                "returnByValue": True,
                            })
                            if result.get("result", {}).get("type") != "error":
                                logger.info("[Recording] CDP injection OK")
                                injected = True
                            else:
                                logger.warning("[Recording] CDP returned error: %s", result)
                            cdp.detach()
                        except Exception as cdp_err:
                            logger.warning("[Recording] CDP injection failed: %s", cdp_err)

                    # Method 2: Chunked base64 injection
                    if not injected:
                        try:
                            import base64 as _b64
                            encoded = _b64.b64encode(script_with_id.encode("utf-8")).decode("ascii")
                            p.evaluate("window.__th_encoded_script = ''")
                            chunk_size = 4000
                            for i in range(0, len(encoded), chunk_size):
                                chunk = encoded[i:i + chunk_size]
                                p.evaluate('window.__th_encoded_script += "' + chunk + '"')
                            p.evaluate("(0,eval)(atob(window.__th_encoded_script))")
                            logger.info("[Recording] Chunked base64 injection OK")
                            injected = True
                        except Exception as chunk_err:
                            logger.warning("[Recording] Chunked injection failed: %s", chunk_err)

                    # Method 3: Direct page.evaluate (original, fallback)
                    if not injected:
                        try:
                            p.evaluate(script_with_id)
                            logger.info("[Recording] Direct evaluate injection OK")
                            injected = True
                        except Exception as eval_err:
                            logger.error("[Recording] All injection methods failed. Last error: %s", eval_err)

                    if injected:
                        logger.info("[Recording] Recorder active on %s", p.url)

                except Exception as e:
                    logger.warning("[Recording] Script injection failed: %s", e)
            context.on("page", lambda p: (
                inject_recorder(p),
                p.on("framenavigated", lambda f: inject_recorder(f.page) if f == f.page.main_frame else None)
            ))
            # Capture console messages and extract actions from recorder
            def on_console(msg):
                try:
                    txt = msg.text
                    try:
                        logger.info("[Browser Console] %s: %s", msg.type, txt)
                    except Exception:
                        logger.info("[Browser Console] %s: (encoding error)", msg.type)
                except Exception:
                    pass
            page.on("console", on_console)
            def on_page_error(err):
                logger.error(f"[Browser Error] {err}")
            page.on("pageerror", on_page_error)

            # Use add_init_script for reliable console capture across navigations
            safe_session_id = json.dumps(str(session_id))
            safe_token = json.dumps(str(auth_token or ""))
            script_with_id = RECORDER_SCRIPT.replace("%%SESSION_ID_JSON%%", safe_session_id).replace("%%AUTH_TOKEN_JSON%%", safe_token)
            page.add_init_script(script_with_id)
            logger.info("[Recording] Init script registered (%d chars)", len(script_with_id))

            page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
            logger.info("[Recording] Page loaded: %s", page.url)

            # Also inject via CDP as fallback for the current page
            inject_recorder(page)
            logger.info(f"[Recording] Initial injection done, waiting for user actions...")
            # Store page reference for polling loop
            with _session_lock:
                if session_id in _active_sessions:
                    _active_sessions[session_id]["page"] = page

            page.on("framenavigated", lambda f: inject_recorder(f.page) if f == f.page.main_frame else None)

            update_status("recording")
            logger.info("[Recording] Session %s -> %s", session_id, start_url)


            stop_event = _active_sessions.get(session_id, {}).get("stop_event")
            logger.info("[Recording] Starting action polling loop for session %s", session_id)

            # Python-side polling: read actions from browser every 1 second
            import time as _poll_time
            last_action_count = 0
            while stop_event and not stop_event.is_set():
                try:
                    # Read window.__testhub_actions from the browser
                    raw = page.evaluate("JSON.stringify((window.__testhub_actions || []).slice(" + str(last_action_count) + "))")
                    if raw and raw != "[]":
                        import json as _json
                        new_actions = _json.loads(raw)
                        if new_actions:
                            with _session_lock:
                                sd = _active_sessions.get(session_id)
                                if sd:
                                    sd["actions"].extend(new_actions)
                                    last_action_count += len(new_actions)
                                    logger.info("[Recording] Poll captured %d new actions (total: %d)", len(new_actions), len(sd["actions"]))
                except Exception as poll_err:
                    # Page might be navigating, just continue
                    if "Execution context was destroyed" not in str(poll_err) and "Target closed" not in str(poll_err):
                        logger.warning("[Recording] Poll error: %s", poll_err)
                try:
                    stop_event.wait(timeout=1.0)
                except Exception:
                    pass

        except Exception as e:
            error_msg = str(e)
            logger.error(f"褰曞埗閿欒 [{session_id}]: {error_msg}")
            if session_id in _active_sessions:
                _active_sessions[session_id]["error"] = error_msg
            update_status("error", error_msg)
        finally:
            try:
                # Close context/browser (handle persistent context where browser==context)
                if context and browser and context is not browser:
                    context.close()
                    browser.close()
                elif context:
                    context.close()
                elif browser:
                    browser.close()
                if pw: pw.stop()
            except Exception:
                pass
            # 纭繚浼氳瘽宸叉竻鐞嗗悗鍐嶅仠姝㈠綍鍒?
            with _session_lock:
                if session_id in _active_sessions:
                    _active_sessions[session_id]["browser_closed"] = True

    @classmethod
    def stop_recording(cls, session_id):
        with _session_lock:
            session_data = _active_sessions.get(session_id)
            if not session_data:
                # 濡傛灉浼氳瘽涓嶅瓨鍦ㄤ簬鍐呭瓨锛屾煡璇㈡暟鎹簱
                try:
                    from .models import RecordingSession
                    s = RecordingSession.objects.get(session_id=session_id)
                    return {"success": True, "actions": s.recorded_actions or [], "error": s.error_message}
                except Exception:
                    return {"success": False, "error": "录制会话未找到"}
            stop_event = session_data.get("stop_event")
            if stop_event:
                stop_event.set()

        # 绛夊緟褰曞埗绾跨▼缁撴潫
        import time as _time
        for _ in range(30):
            with _session_lock:
                sd = _active_sessions.get(session_id)
                if not sd or sd.get("browser_closed"):
                    break
            _time.sleep(0.5)

        with _session_lock:
            session_data = _active_sessions.get(session_id, {})

        actions = session_data.get("actions", [])
        error = session_data.get("error")

        # 绛夊緟褰曞埗杩涚▼瀹屾垚
        thread = session_data.get("thread")
        if thread:
            thread.join(timeout=5)

        # 鏀堕泦褰曞埗缁撴灉
        try:
            from .models import RecordingSession
            s = RecordingSession.objects.get(session_id=session_id)
            s.recorded_actions = actions
            s.status = "error" if error else "stopped"
            if error:
                s.error_message = error
            s.save(update_fields=["recorded_actions", "status", "error_message", "updated_at"])
        except Exception as e:
            logger.error(f"鑾峰彇褰曞埗缁撴灉澶辫触: {e}")

        # 淇濆瓨鍔ㄤ綔
        with _session_lock:
            _active_sessions.pop(session_id, None)

        return {"success": True, "actions": actions, "error": error}

    @classmethod
    def add_actions(cls, session_id, actions):
        with _session_lock:
            session_data = _active_sessions.get(session_id)
            if not session_data:
                return {"success": False, "error": "录制会话未找到"}
            session_data["actions"].extend(actions)
        return {"success": True, "count": len(actions)}

    @classmethod
    def get_actions(cls, session_id):
        with _session_lock:
            session_data = _active_sessions.get(session_id)
            if not session_data:
                return []
            return list(session_data["actions"])

    @classmethod
    def get_status(cls, session_id):
        with _session_lock:
            session_data = _active_sessions.get(session_id)
            if not session_data:
                return {"status": "unknown", "actions_count": 0}
            return {"status": session_data["session"].status, "actions_count": len(session_data["actions"]), "error": session_data.get("error")}

    @classmethod
    def save_as_test_case(cls, session_id, test_case_name, project_id, user=None, target_test_case_id=None, selected_action_indexes=None):
        from .models import RecordingSession, TestCase, TestCaseStep, Element, LocatorStrategy, UiProject

        try:
            session = RecordingSession.objects.get(session_id=session_id)
        except RecordingSession.DoesNotExist:
            return {"success": False, "error": "录制会话不存在"}

        actions = session.recorded_actions or []
        if not actions:
            return {"success": False, "error": "没有录制到任何操作"}

        try:
            project = UiProject.objects.get(id=project_id)
        except UiProject.DoesNotExist:
            return {"success": False, "error": "项目不存在"}

        selected_indexes = None
        if isinstance(selected_action_indexes, list):
            selected_indexes = []
            for index in selected_action_indexes:
                try:
                    selected_indexes.append(int(index))
                except (TypeError, ValueError):
                    continue

        if selected_indexes is not None and selected_indexes:
            actions = [action for idx, action in enumerate(actions) if idx in selected_indexes]
        elif selected_indexes == []:
            return {"success": False, "error": "没有选择要保存的录制步骤"}

        clean_actions = cls._clean_actions(actions)
        if not clean_actions:
            return {"success": False, "error": "过滤后没有可保存的录制步骤"}

        created_steps = 0
        try:
            with transaction.atomic():
                append_mode = bool(target_test_case_id)
                if append_mode:
                    try:
                        test_case = TestCase.objects.select_for_update().get(id=target_test_case_id, project=project)
                    except TestCase.DoesNotExist:
                        return {"success": False, "error": "目标测试用例不存在"}
                    start_step_number = test_case.steps.count()
                else:
                    test_case = TestCase.objects.create(
                        name=test_case_name,
                        description=f"来自录制会话 {session_id} 的测试用例",
                        project=project,
                        status="draft",
                        priority="medium",
                        created_by=user,
                    )
                    start_step_number = 0

                for i, action in enumerate(clean_actions):
                    strategy_name = action.get("locator_strategy", "css")
                    strategy_id = cls.get_locator_strategy_id(strategy_name)
                    element_type = cls.infer_element_type(action.get("element_tag", ""), action.get("element_type", ""), action.get("element_text", ""))
                    element_name = cls.generate_element_name(action)

                    element, created = Element.objects.get_or_create(
                        project=project,
                        locator_strategy_id=strategy_id,
                        locator_value=action.get("locator_value", ""),
                        defaults={
                            "name": element_name,
                            "description": action.get("locator_description", ""),
                            "element_type": element_type,
                            "page": action.get("page_url", ""),
                            "validation_status": "UNKNOWN",
                            "created_by": user,
                        },
                    )

                    action_type = action.get("action_type", "click")
                    is_optional, optional_note = cls.infer_optional_step(action)
                    TestCaseStep.objects.create(
                        test_case=test_case,
                        step_number=start_step_number + i + 1,
                        action_type=action_type,
                        element=element,
                        input_value=action.get("input_value", ""),
                        wait_time=1000,
                        is_optional=is_optional,
                        optional_note=optional_note,
                        description=cls.generate_step_description(action),
                    )
                    created_steps += 1
        except Exception as e:
            logger.error("保存录制步骤失败，已回滚: %s", e, exc_info=True)
            return {"success": False, "error": f"保存录制步骤失败: {e}"}

        session.status = "saved"
        session.save(update_fields=["status", "updated_at"])

        return {
            "success": True,
            "test_case_id": test_case.id,
            "test_case_name": test_case.name,
            "steps_created": created_steps,
            "save_mode": "append" if append_mode else "create",
        }

    @classmethod
    def _clean_actions(cls, actions):
        if not actions:
            return []
        cleaned = []
        for action in actions:
            at = action.get("action_type")
            if at == "fill" and cleaned and cleaned[-1].get("action_type") == "fill":
                if cleaned[-1].get("locator_value") == action.get("locator_value"):
                    cleaned[-1] = action
                    continue
            cleaned.append(action)
        return cleaned

    @classmethod
    def infer_optional_step(cls, action):
        action_type = str(action.get("action_type", "")).lower()
        if action_type != "click":
            return False, ""

        text = " ".join([
            str(action.get("locator_value", "")),
            str(action.get("locator_description", "")),
            str(action.get("element_text", "")),
            str(action.get("page_url", "")),
        ]).lower()

        keywords = [
            "banner", "popup", "modal", "dialog", "close", "dismiss", "guide",
            "notice", "tip", "toast", "floating", "overlay", "mask",
            "弹窗", "关闭", "公告", "浮层", "提示", "引导", "横幅", "遮罩"
        ]

        if any(keyword in text for keyword in keywords):
            return True, "一次性弹窗/浮层关闭，未出现时自动跳过"

        locator_value = str(action.get("locator_value", "")).strip().lower()
        element_text = str(action.get("element_text", "")).strip()
        if locator_value.endswith("> i") and not element_text:
            return True, "关闭类图标点击，未出现时自动跳过"

        return False, ""
