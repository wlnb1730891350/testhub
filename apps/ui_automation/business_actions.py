"""Business/page-object actions for TestHub AI UI automation.

These actions are intentionally deterministic. Natural language is compiled into
these semantic actions before execution, so high-risk NN flows no longer depend
only on fuzzy DOM guessing.
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Dict, Optional
from uuid import uuid4

from .click_constraints import extract_click_constraints


ActionResult = Dict[str, Any]
HALL_RUNTIME_CONTEXTS: Dict[int, Dict[str, str]] = {}


def _ok(message: str, element: Optional[Dict[str, Any]] = None) -> ActionResult:
    return {'status': 'completed', 'message': message, 'element': element or {}}


def _fail(message: str, element: Optional[Dict[str, Any]] = None) -> ActionResult:
    return {'status': 'failed', 'error': message, 'message': message, 'element': element or {}}


def _is_generated_article_title(step: Dict[str, Any], value: str) -> bool:
    """Only replace a title that this run generated as disposable test data."""
    source = str((step.get('_variable_sources') or {}).get('input_value') or '')
    return '${' in source and 'timestamp' in source and bool(str(value or '').strip())


def _safe_generated_article_title() -> str:
    """Keep synthetic titles unique without a phone-like long digit sequence."""
    return f'公告更新{uuid4().hex[:8]}'


def _safe_generated_article_body() -> str:
    """Use a natural, non-repeated body for disposable article test data."""
    variants = (
        '社区日常通知：请关注公告栏中的最新安排。',
        '社区内容更新说明：相关信息已同步至本页。',
        '社区活动提醒：欢迎成员在合适时间参与讨论。',
    )
    return f'{variants[uuid4().int % len(variants)]} 标识{uuid4().hex[:4].upper()}'


def _log(execution_record, message: str) -> None:
    if execution_record is not None:
        execution_record.logs += '  ' + message + chr(10)


def _community_identity_from_card_detail(detail: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Persist the concrete name and ID from a clicked community result card."""
    text = str((detail or {}).get('text') or '').strip()
    match = re.search(r'(?<!\d)(\d{5,})(?!\d)', text)
    if not match:
        return {}
    return {
        'name': text[:match.start()].strip(' -|:：'),
        'id': match.group(1),
        'card_text': text,
    }


async def _first_visible(page, selectors, timeout=1000):
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if await loc.count() > 0 and await loc.is_visible(timeout=timeout):
                return selector, loc
        except Exception:
            continue
    return None, None


async def _fill_and_verify(locator, value: str) -> bool:
    try:
        await locator.fill(value, timeout=10000)
    except Exception:
        await locator.type(value, timeout=10000)
    try:
        actual = await locator.input_value(timeout=1000)
        return str(value) in str(actual)
    except Exception:
        return True


async def _find_best_login_dialog(page):
    """优先定位真正的登录弹窗，避免把普通页面输入框当成登录表单。"""
    try:
        result = await page.evaluate(r"""() => {
            const visible = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
            };
            const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
            const roots = Array.from(document.querySelectorAll('[role="dialog"], .nn-dialog, .nn-modal, .modal, .dialog, [class*="dialog" i], [class*="modal" i]')).filter(visible);
            const candidates = [];
            for (const root of roots) {
                const text = norm(root.innerText || root.textContent || '');
                const cls = String(root.className || '');
                const r = root.getBoundingClientRect();
                const inputs = Array.from(root.querySelectorAll('input')).filter(visible);
                const phoneInput = inputs.find(el => /请输入手机|手机号|手机|phone|mobile/i.test((el.getAttribute('placeholder') || '') + ' ' + (el.getAttribute('name') || '')));
                const codeInput = inputs.find(el => /验证码|校验码|动态码|code|captcha/i.test((el.getAttribute('placeholder') || '') + ' ' + (el.getAttribute('name') || '')));
                const submitBtn = Array.from(root.querySelectorAll('button,[role="button"],a,.nn-button,.el-button')).filter(visible).find(el => /登录|登陆|注册|login|sign/i.test(norm(el.innerText || el.textContent || el.getAttribute('aria-label') || '')));
                let score = 0;
                if (/登录|登陆|注册|验证码|手机号|手机号码/.test(text)) score += 1500;
                if (phoneInput) score += 2000;
                if (codeInput) score += 1800;
                if (submitBtn) score += 1200;
                score += Math.min(inputs.length, 6) * 80;
                if (/search|搜索社区|全部社区|用户昵称|nn号/i.test(text + ' ' + cls)) score -= 2500;
                if (r.width < 260 || r.height < 180) score -= 1000;
                if (score <= 0) continue;
                const token = 'ai_nn_login_dialog_' + Date.now() + '_' + Math.random().toString(36).slice(2);
                root.setAttribute('data-ai-automation-login-dialog', token);
                candidates.push({
                    selector: '[data-ai-automation-login-dialog=\"' + token + '\"]',
                    score,
                    text: text.slice(0, 200),
                    cls: cls.slice(0, 160),
                    rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)},
                    hasPhoneInput: !!phoneInput,
                    hasCodeInput: !!codeInput,
                    hasSubmitBtn: !!submitBtn,
                    inputCount: inputs.length,
                });
            }
            candidates.sort((a, b) => b.score - a.score);
            return candidates[0] || null;
        }""")
        return result
    except Exception:
        return None


async def _first_visible_in_root(page, root_selector, selectors, timeout=1000):
    if not root_selector:
        return None, None
    for selector in selectors:
        scoped = f'{root_selector} {selector}'
        try:
            loc = page.locator(scoped).first
            if await loc.count() > 0 and await loc.is_visible(timeout=timeout):
                return scoped, loc
        except Exception:
            continue
    return None, None


async def _find_login_field(page, selectors, timeout=1000):
    dialog = await _find_best_login_dialog(page)
    if dialog and dialog.get('selector'):
        scoped_selector, scoped_loc = await _first_visible_in_root(page, dialog['selector'], selectors, timeout=timeout)
        if scoped_loc:
            return scoped_selector, scoped_loc, dialog
    selector, loc = await _first_visible(page, selectors, timeout=timeout)
    return selector, loc, dialog


async def _visible_login_form_state(page) -> Dict[str, Any]:
    """Return whether a real visible login form/dialog exists on the current page."""
    try:
        return await page.evaluate(r"""() => {
            const visible = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
            };
            const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
            const dialogs = Array.from(document.querySelectorAll('[role="dialog"], .nn-dialog, .nn-modal, .modal, .dialog, [class*="dialog" i], [class*="modal" i]')).filter(visible);
            const inputs = Array.from(document.querySelectorAll('input')).filter(visible);
            const phoneInputs = inputs.filter(el => /请输入手机|手机号|手机|phone|mobile/i.test((el.getAttribute('placeholder') || '') + ' ' + (el.getAttribute('name') || '')));
            const codeInputs = inputs.filter(el => /验证码|校验码|动态码|code|captcha/i.test((el.getAttribute('placeholder') || '') + ' ' + (el.getAttribute('name') || '')));
            const passwordInputs = inputs.filter(el => /密码|password/i.test((el.getAttribute('placeholder') || '') + ' ' + (el.getAttribute('name') || ' ' + (el.getAttribute('type') || ''))));
            const submitButtons = Array.from(document.querySelectorAll('button,[role="button"],a,.nn-button,.el-button')).filter(visible).filter(el => /登录|登陆|注册|login|sign/i.test(norm(el.innerText || el.textContent || el.getAttribute('aria-label') || '')));
            const hasLoginSignals = !!(phoneInputs.length || codeInputs.length || passwordInputs.length || submitButtons.length);
            return {
                passed: hasLoginSignals,
                reason: hasLoginSignals ? '' : '当前页面未检测到真实登录表单/弹窗，禁止继续执行登录提交',
                evidence: {
                    url: location.href,
                    title: document.title,
                    dialogCount: dialogs.length,
                    phoneInputCount: phoneInputs.length,
                    codeInputCount: codeInputs.length,
                    passwordInputCount: passwordInputs.length,
                    submitButtonCount: submitButtons.length,
                    bodyText: norm((document.body && document.body.innerText || '').slice(0, 500)),
                }
            };
        }""")
    except Exception as e:
        return {'passed': False, 'reason': '登录表单检测异常: ' + str(e)[:200], 'evidence': {}}


class NNPageActions:
    """Page object for the NN web flows used by current AI UI cases."""

    LOGIN_ENTRY_SELECTORS = [
        'img[alt*="默认头像"]',
        'img[alt*="头像"]',
        'img[alt*="avatar" i]',
        'header [class*="avatar" i]',
        'header [class*="user" i]',
        '[class*="avatar" i]',
        'a:has-text("登录")',
        'button:has-text("登录")',
    ]

    PHONE_SELECTORS = [
        'input[placeholder*="请输入手机"]',
        'input[placeholder*="手机号"]',
        'input[placeholder*="手机"]',
        'input[placeholder*="phone" i]',
        'input[placeholder*="mobile" i]',
        'input[name*="phone" i]',
        'input[name*="mobile" i]',
        'input[type="tel"]',
        'input[type="number"]',
    ]

    CODE_SELECTORS = [
        'input[placeholder*="验证码"]',
        'input[placeholder*="校验码"]',
        'input[placeholder*="动态码"]',
        'input[placeholder*="code" i]',
        'input[name*="code" i]',
        'input[name*="captcha" i]',
        'input[type="number"]',
    ]

    PASSWORD_SELECTORS = [
        'input[type="password"]',
        'input[placeholder*="密码"]',
        'input[placeholder*="password" i]',
        'input[name*="password" i]',
    ]

    TOP_SEARCH_TRIGGERS = [
        'header .cursor-pointer:has(.nicon-a-search-linesousuo-xianxing)',
        'header [class*="cursor-pointer"]:has([class*="search" i])',
        'header [class*="search" i]',
        '.appHeader .cursor-pointer:has(.nicon-a-search-linesousuo-xianxing)',
        '.appHeader [class*="search" i]',
    ]

    TOP_SEARCH_INPUTS = [
        'input[placeholder*="搜索社区"]',
        'input[placeholder*="用户昵称"]',
        'input[placeholder*="NN号"]',
        '.nn-input--large input[placeholder*="搜索"]',
    ]

    def __init__(self, page, execution_record=None):
        self.page = page
        self.execution_record = execution_record

    async def _permission_state(self, step) -> ActionResult:
        """Read permission state inside the identified subject scope.

        A permission is considered known only when the page exposes an
        explicit checked/selected/granted/enabled signal.  Mere presence of
        the permission label is intentionally insufficient because menus can
        show an option before it is granted.
        """
        payload = {
            'subjectText': str(step.get('subject_text') or step.get('target_text') or '').strip(),
            'permissionText': str(step.get('permission_text') or step.get('permission_key') or '').strip(),
            'targetSelector': str(step.get('target_selector') or '').strip(),
            'scopeSelector': str(step.get('permission_scope_selector') or '').strip(),
            'permissionSelector': str(step.get('permission_state_selector') or '').strip(),
        }
        if not payload['subjectText'] or not payload['permissionText']:
            return _fail('权限用例必须明确指定授权对象和权限项', {'payload': payload})
        try:
            state = await self.page.evaluate(r'''(payload) => {
                const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
                const visible = el => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
                };
                const exact = (el, value) => norm(el?.innerText || el?.textContent || el?.getAttribute('aria-label')) === value;
                const all = Array.from(document.querySelectorAll('*')).filter(visible);
                let subject = null;
                if (payload.targetSelector) subject = document.querySelector(payload.targetSelector);
                if (!subject) subject = all.filter(el => exact(el, payload.subjectText)).sort((a, b) => norm(a.innerText).length - norm(b.innerText).length)[0];
                if (!subject) return {known: false, authorized: false, reason: '未找到授权对象', payload};

                let scope = payload.scopeSelector ? subject.closest(payload.scopeSelector) : null;
                if (!scope) {
                    const roots = [];
                    let node = subject;
                    for (let depth = 0; node && depth < 8; depth += 1, node = node.parentElement) {
                        const text = norm(node.innerText || node.textContent || '');
                        if (text.includes(payload.subjectText) && text.length <= 1200) {
                            if (/^(TR|LI|ARTICLE|SECTION|FORM)$/.test(node.tagName) || node.getAttribute('role') === 'row' || /card|item|member|user|role|permission|dialog/i.test(String(node.className || ''))) roots.push(node);
                        }
                    }
                    scope = roots.sort((a, b) => a.getBoundingClientRect().width * a.getBoundingClientRect().height - b.getBoundingClientRect().width * b.getBoundingClientRect().height)[0] || subject.parentElement || subject;
                }
                const permissionNodes = payload.permissionSelector
                    ? Array.from(scope.querySelectorAll(payload.permissionSelector)).filter(visible)
                    : Array.from(scope.querySelectorAll('*')).filter(el => visible(el) && exact(el, payload.permissionText));
                const stateOf = el => {
                    const attrs = ['aria-checked','aria-selected','data-authorized','data-granted','data-enabled','data-state'].map(k => String(el.getAttribute(k) || '').toLowerCase());
                    const cls = String(el.className || '').toLowerCase();
                    const checked = !!el.matches?.('input:checked,[checked]');
                    const positive = attrs.some(v => /true|checked|selected|granted|authorized|enabled|active/.test(v)) || checked || /checked|selected|granted|authorized|enabled|active/.test(cls);
                    const negative = attrs.some(v => /false|unchecked|unselected|revoked|disabled|inactive/.test(v)) || /unchecked|unselected|revoked|disabled|inactive/.test(cls);
                    return {positive, negative, attrs, cls: cls.slice(0, 180)};
                };
                const states = permissionNodes.map(el => stateOf(el));
                const known = states.some(item => item.positive || item.negative);
                const authorized = states.some(item => item.positive) && !states.every(item => item.negative);
                const token = 'ai-permission-scope-' + Date.now() + '-' + Math.random().toString(36).slice(2);
                scope.setAttribute('data-ai-permission-scope', token);
                return {
                    known, authorized, subject: payload.subjectText, permission: payload.permissionText,
                    scopeSelector: '[data-ai-permission-scope="' + token + '"]',
                    permissionCount: permissionNodes.length,
                    states: states.slice(0, 8),
                };
            }''', payload)
            if not state or not state.get('known'):
                return _fail(
                    '无法确认授权前状态，已拒绝执行权限变更（请提供权限状态选择器或明确状态标识）',
                    {'state': state or {}, 'payload': payload},
                )
            return _ok('已读取权限状态', {'permission_state': state})
        except Exception as exc:
            return _fail(f'读取权限状态失败: {str(exc)[:220]}', {'payload': payload})

    async def _click_permission_control(self, step, mode: str, state: Dict[str, Any]) -> ActionResult:
        labels = {
            'grant': r'添加|授予|授权|赋予|开启|分配|grant|authorize|assign',
            'revoke': r'移除|撤销|取消授权|删除权限|关闭|remove|revoke|unassign',
        }[mode]
        payload = {
            'scopeSelector': state.get('scopeSelector') or step.get('permission_scope_selector') or '',
            'permissionText': str(step.get('permission_text') or step.get('permission_key') or '').strip(),
            'explicitSelector': str(step.get(f'{mode}_selector') or '').strip(),
            'labels': labels,
        }
        try:
            scan = await self.page.evaluate(r'''(payload) => {
                const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
                const visible = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0'; };
                const scope = payload.scopeSelector ? document.querySelector(payload.scopeSelector) : document.body;
                if (!scope) return {found: false, reason: '权限作用域已消失'};
                let candidate = payload.explicitSelector ? scope.querySelector(payload.explicitSelector) : null;
                if (!candidate) {
                    const matcher = new RegExp(payload.labels, 'i');
                    const candidates = Array.from(scope.querySelectorAll('button,[role="button"],a,input[type="checkbox"],label,[class*="cursor-pointer" i]'))
                        .filter(visible).map(el => {
                            const text = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || '');
                            const cls = String(el.className || '');
                            let score = matcher.test(text) ? 5000 : 0;
                            if (text.includes(payload.permissionText)) score += 900;
                            if (/permission|authorize|grant|revoke|role|access/i.test(text + ' ' + cls)) score += 700;
                            if (el.matches('input[type="checkbox"]:checked')) score -= 5000;
                            return {el, text, score};
                        }).filter(item => item.score >= 5000).sort((a, b) => b.score - a.score);
                    candidate = candidates[0]?.el || null;
                }
                if (!candidate) return {found: false, reason: '未找到明确的权限变更控件'};
                const token = 'ai-permission-control-' + Date.now() + '-' + Math.random().toString(36).slice(2);
                candidate.setAttribute('data-ai-permission-control', token);
                return {found: true, selector: '[data-ai-permission-control="' + token + '"]', text: norm(candidate.innerText || candidate.textContent || candidate.getAttribute('aria-label') || candidate.getAttribute('title') || '')};
            }''', payload)
            if not scan or not scan.get('found'):
                return _fail(scan.get('reason') if scan else '未找到权限变更控件', {'scan': scan or {}, 'payload': payload})
            locator = self.page.locator(scan['selector']).first
            await locator.click(timeout=8000)
            await asyncio.sleep(0.5)
            return _ok(f'已执行{("授权" if mode == "grant" else "撤销")}控件', {'scan': scan})
        except Exception as exc:
            return _fail(f'执行权限{("授权" if mode == "grant" else "撤销")}控件失败: {str(exc)[:220]}', {'payload': payload})

    async def grant_permission(self, step, permission_cleanup=None) -> ActionResult:
        before_result = await self._permission_state(step)
        if before_result.get('status') != 'completed':
            return before_result
        before = (before_result.get('element') or {}).get('permission_state') or {}
        if before.get('authorized'):
            return _ok('权限原本已存在，本次不登记回收', {'before': before, 'changed': False})
        click_result = await self._click_permission_control(step, 'grant', before)
        if click_result.get('status') != 'completed':
            return click_result
        after_result = await self._permission_state(step)
        after = (after_result.get('element') or {}).get('permission_state') or {}
        # Register immediately after a successful mutation click.  If the
        # follow-up read is interrupted by a dialog/network delay, cleanup is
        # still attempted; otherwise a partially completed grant could leak
        # into the next independent case.
        if after_result.get('status') != 'completed' or not after:
            if permission_cleanup is not None:
                permission_cleanup.register(step, before, after or {'known': False, 'authorized': None})
            return _fail('点击授权后无法确认权限是否生效，已登记保守回收', {'before': before, 'after': after, 'click': click_result})
        if not after.get('authorized'):
            return _fail('点击授权后未验证到权限已生效', {'before': before, 'after': after, 'click': click_result})
        if permission_cleanup is not None:
            permission_cleanup.register(step, before, after)
        return _ok('权限已添加并验证生效，已登记用例结束回收', {'before': before, 'after': after, 'changed': True})

    async def revoke_permission(self, step) -> ActionResult:
        entry = step.get('cleanup_entry') or {}
        before = entry.get('before') or {}
        if before.get('authorized'):
            return _fail('拒绝回收：授权前状态已是已授权，防止误删原有权限', {'before': before})
        current_result = await self._permission_state(step)
        if current_result.get('status') != 'completed':
            return current_result
        current = (current_result.get('element') or {}).get('permission_state') or {}
        if not current.get('authorized'):
            return _ok('权限已不存在，无需重复回收', {'current': current})
        click_result = await self._click_permission_control(step, 'revoke', current)
        if click_result.get('status') != 'completed':
            return click_result
        after_result = await self._permission_state(step)
        after = (after_result.get('element') or {}).get('permission_state') or {}
        if after_result.get('status') != 'completed' or after.get('authorized'):
            return _fail('点击撤销后仍检测到权限存在', {'before': current, 'after': after, 'click': click_result})
        return _ok('权限已撤销并验证回收完成', {'before': current, 'after': after})

    async def _already_logged_in(self) -> Optional[ActionResult]:
        state = await evaluate_login_success(self.page)
        if state.get('passed'):
            _log(self.execution_record, f'BUSINESS_ACTION login_state_reused evidence={state.get("evidence")}')
            return _ok('已存在登录态，跳过重复登录', {'login_state': state})
        return None

    async def _ensure_article_interaction_access(self) -> ActionResult:
        """Leave the read-only community shell before operating article controls.

        A fresh authenticated context can still open a community in its
        browse-only state.  In that state the article feed is visible but the
        publish, management, and comment controls are deliberately absent.
        Following the community is the product's own transition to an
        interactive state, so perform and verify it here instead of assuming a
        preceding case has already done so.
        """
        try:
            state = await self.page.evaluate(r'''() => {
                const visible = el => { const r=el.getBoundingClientRect(), s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0'; };
                const norm = value => String(value || '').replace(/\s+/g, '').trim();
                const text = String(document.body?.innerText || '');
                const actionNodes = Array.from(document.querySelectorAll('button,[role="button"],a,div,span')).filter(visible);
                const follow = actionNodes.map(source => {
                    const label=norm(source.innerText||source.textContent||source.getAttribute('aria-label')||'');
                    if (!/^(?:关注社区|关注)$/.test(label)) return null;
                    const owner=source.closest('button,a,[role="button"],[class*="cursor-pointer" i],[class*="clickable" i]') || source;
                    const r=owner.getBoundingClientRect();
                    return r.width>=48&&r.height>=20 ? owner : null;
                }).find(Boolean);
                const interactive = /(?:取消关注|已关注|内容管理|发布)/.test(text);
                if (!follow) return {interactive, followRequired:false, browseOnly:/当前浏览状态|关注后可参与互动/.test(text), text:text.slice(0,500)};
                const token='ai_article_follow_'+Date.now()+'_'+Math.random().toString(36).slice(2);
                follow.setAttribute('data-ai-article-follow', token);
                return {interactive, followRequired:true, browseOnly:/当前浏览状态|关注后可参与互动/.test(text), selector:'[data-ai-article-follow="'+token+'"]'};
            }''')
            _log(self.execution_record, f'BUSINESS_ACTION article_interaction_access initial={state}')
            if not state.get('followRequired'):
                return _ok('文章社区已处于可互动状态', {'state': state})

            await self.page.locator(state['selector']).click(timeout=5000)
            deadline = time.monotonic() + 10
            last = state
            while time.monotonic() < deadline:
                last = await self.page.evaluate(r'''() => {
                    const text=String(document.body?.innerText || '');
                    return {
                        browseOnly:/当前浏览状态|关注后可参与互动/.test(text),
                        interactive:/(?:取消关注|已关注|内容管理|发布)/.test(text),
                        text:text.slice(0,700),
                    };
                }''')
                if not last.get('browseOnly') and last.get('interactive'):
                    return _ok('已关注社区并进入文章可互动状态', {'before': state, 'after': last})
                await asyncio.sleep(.25)

            # Some community shells persist follow state but do not re-render
            # their controls in place. Reload once to verify the authoritative
            # state before treating the interaction setup as failed.
            try:
                await self.page.reload(wait_until='domcontentloaded', timeout=15000)
                await asyncio.sleep(.8)
                last = await self.page.evaluate(r'''() => {
                    const text=String(document.body?.innerText || '');
                    return {
                        browseOnly:/当前浏览状态|关注后可参与互动/.test(text),
                        interactive:/(?:取消关注|已关注|内容管理|发布)/.test(text),
                        text:text.slice(0,700),
                    };
                }''')
                if not last.get('browseOnly') and last.get('interactive'):
                    return _ok('已关注社区并在刷新后确认可互动状态', {'before': state, 'after': last, 'reloaded': True})
            except Exception as exc:
                last = {**(last or {}), 'reloadError': str(exc)[:200]}
            return _fail('已尝试关注社区，但页面仍停留在只读浏览状态', {'before': state, 'after': last})
        except Exception as exc:
            return _fail(f'初始化文章可互动状态失败: {str(exc)[:200]}')

    async def click_community_plugin(self, step) -> ActionResult:
        """Navigate a left community plugin and wait for its selected state to converge."""
        target = str(step.get('target_text') or step.get('input_value') or '').strip()
        aliases = {
            '成员大厅': ('成员大厅', '全员大厅'),
            '全员大厅': ('全员大厅', '成员大厅'),
            'PUBG福利商店': ('PUBG福利商店', 'NN商店'),
            'NN商店': ('NN商店', 'PUBG福利商店'),
        }.get(target, (target,))
        # Imported case titles sometimes retain editorial suffixes such as
        # “(修改后)”.  They identify the same stable plugin, not a second UI
        # entry.  Keep both texts as exact alternatives rather than fuzzy
        # matching arbitrary plugin names.
        stable_target = re.sub(r'[（(][^（）()]*[）)]$', '', target).strip()
        if stable_target and stable_target != target:
            aliases = tuple(dict.fromkeys((*aliases, stable_target)))
        if not target:
            return _fail('社区插件切换缺少目标名称')
        try:
            scan = await self.page.evaluate(r'''(payload) => {
                const visible = el => { const r=el.getBoundingClientRect(), s=getComputedStyle(el); return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0'; };
                const norm = value => String(value || '').replace(/\s+/g, '').trim();
                const targets = new Set(payload.aliases.map(norm));
                const leaves = Array.from(document.querySelectorAll('a,button,[role="menuitem"],[role="tab"],div,span')).filter(visible).filter(el => {
                    const r=el.getBoundingClientRect();
                    return r.left < innerWidth*.38 && targets.has(norm(el.innerText||el.textContent||''));
                });
                const candidates = leaves.map(source => {
                    let owner=source.closest('a,button,[role="menuitem"],[role="tab"],[class*="cursor-pointer" i],[class*="clickable" i]') || source;
                    for (let parent=owner.parentElement, depth=0; parent&&depth<5; parent=parent.parentElement, depth+=1) {
                        const r=parent.getBoundingClientRect();
                        if (visible(parent) && r.left < innerWidth*.38 && r.width<=520 && r.height<=110) {
                            const cls=String(parent.className||'');
                            if (/cursor-pointer|clickable|menu|nav|item|plugin/i.test(cls)) { owner=parent; break; }
                        }
                    }
                    const r=owner.getBoundingClientRect();
                    const cls=String(owner.className||'')+' '+String(source.className||'');
                    const score=(owner.tagName==='A'||owner.tagName==='BUTTON'?1200:0)+(/cursor-pointer|clickable|menu|nav|item|plugin/i.test(cls)?1000:0)+(r.width>=80&&r.height>=24?300:0);
                    return {owner,text:norm(source.innerText||source.textContent||''),cls,r,score};
                }).sort((a,b)=>b.score-a.score);
                const best=candidates[0];
                if(!best)return {found:false, aliases:payload.aliases, candidates:[]};
                const main=Array.from(document.querySelectorAll('main,[role="main"],#app>div')).filter(visible).map(el=>String(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim()).filter(Boolean).sort((a,b)=>b.length-a.length)[0] || '';
                const token='ai_community_plugin_'+Date.now()+'_'+Math.random().toString(36).slice(2); best.owner.setAttribute('data-ai-community-plugin',token);
                return {found:true,selector:'[data-ai-community-plugin="'+token+'"]',before:{url:location.href,main:main.slice(0,1200)},candidate:{text:best.text,cls:best.cls.slice(0,180),rect:{x:Math.round(best.r.x),y:Math.round(best.r.y),w:Math.round(best.r.width),h:Math.round(best.r.height)}}};
            }''', {'aliases': list(aliases)})
            _log(self.execution_record, f'BUSINESS_ACTION nn_click_community_plugin scan={scan}')
            if not scan.get('found'):
                return _fail(f'未找到左侧社区插件「{target}」', {'scan': scan})
            await self.page.locator(scan['selector']).click(timeout=8000, force=True)
            deadline = time.monotonic() + 12
            last = {}
            while time.monotonic() < deadline:
                last = await self.page.evaluate(r'''(payload) => {
                    const visible = el => { const r=el.getBoundingClientRect(), s=getComputedStyle(el); return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0'; };
                    const norm = value => String(value || '').replace(/\s+/g, '').trim();
                    const selected = Array.from(document.querySelectorAll('a,button,[role="menuitem"],[role="tab"],div,span')).filter(visible).filter(el => {
                        const r=el.getBoundingClientRect(); return r.left < innerWidth*.46 && payload.aliases.map(norm).includes(norm(el.innerText||el.textContent||''));
                    }).some(node => {
                        for(let el=node, depth=0; el&&depth<6; el=el.parentElement, depth+=1) {
                            const cls=String(el.className||'');
                            if(el.getAttribute('aria-selected')==='true' || (el.getAttribute('aria-current') && el.getAttribute('aria-current')!=='false') || /active|selected|current|is-active|is-selected|text-(?:blue|primary|purple|brand)/i.test(cls)) return true;
                        }
                        return false;
                    });
                    const main=Array.from(document.querySelectorAll('main,[role="main"],#app>div')).filter(visible).map(el=>String(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim()).filter(Boolean).sort((a,b)=>b.length-a.length)[0] || '';
                    const mainChanged=main.slice(0,1200)!==(payload.before.main||'') || location.href!==payload.before.url;
                    const loading=/^(加载中|loading|\.{3})$/i.test(main.trim()) || /skeleton|animate-pulse/i.test(String(document.body?.className||''));
                    return {selected,mainChanged,loading,url:location.href,main:main.slice(0,1200)};
                }''', {'aliases': list(aliases), 'before': scan['before']})
                if last.get('selected') and (last.get('mainChanged') or not last.get('loading')):
                    return _ok(f'已切换社区插件「{target}」并确认选中状态', {'scan': scan, 'state': last})
                await asyncio.sleep(.25)
            return _fail(f'点击社区插件「{target}」后页面未收敛到选中状态', {'scan': scan, 'state': last})
        except Exception as exc:
            return _fail(f'切换社区插件「{target}」失败: {str(exc)[:200]}')

    async def _click_article_candidate(self, intent, matcher, success_check=None) -> ActionResult:
        """Click a visible article-surface control with DOM evidence, never fuzzy page-wide text."""
        try:
            access = await self._ensure_article_interaction_access()
            if access.get('status') != 'completed':
                return access
            scan = await self.page.evaluate(r'''(payload) => {
                const visible = (el) => {
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
                };
                const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
                const matcher = new RegExp(payload.matcher, 'i');
                const all = Array.from(document.querySelectorAll('button,[role="button"],a,div,span'));
                const seen = new Set();
                const candidates = all.filter(visible).map(source => {
                    const text = norm(source.innerText || source.textContent || source.getAttribute('aria-label') || '');
                    let el = source.closest('button,a,[role="button"],[class*="cursor-pointer" i],[class*="clickable" i]') || source;
                    if (el === source) {
                        let parent = source.parentElement;
                        const sourceRect = source.getBoundingClientRect();
                        for (let depth = 0; parent && depth < 6; depth += 1, parent = parent.parentElement) {
                            const parentRect = parent.getBoundingClientRect();
                            if (visible(parent)
                                && parentRect.width >= Math.max(90, sourceRect.width * 2)
                                && parentRect.height >= Math.max(32, sourceRect.height * 1.5)
                                && parentRect.width <= 700
                                && parentRect.height <= 220) {
                                el = parent;
                                break;
                            }
                        }
                    }
                    const r = el.getBoundingClientRect();
                    const cls = String(el.className || '') + ' ' + String(source.className || '');
                    let score = 0;
                    if (matcher.test(text)) score += 3000;
                    if (el.tagName === 'BUTTON' || el.getAttribute('role') === 'button') score += 1800;
                    if (/button|cursor-pointer|clickable|action/i.test(cls)) score += 900;
                    if (r.left > innerWidth * 0.22) score += 250;
                    if (r.top >= 0 && r.top < innerHeight && r.left >= 0 && r.left < innerWidth) {
                        const x = Math.min(innerWidth - 1, Math.max(0, r.left + r.width / 2));
                        const y = Math.min(innerHeight - 1, Math.max(0, r.top + r.height / 2));
                        const top = document.elementFromPoint(x, y);
                        if (top && !el.contains(top) && !top.contains(el)) score -= 5000;
                    }
                    if (text.length > 80) score -= 1800;
                    if (score < 3000 || seen.has(el)) return null;
                    seen.add(el);
                    return {el, text, cls, r, score};
                }).filter(Boolean).sort((a, b) => b.score - a.score);
                const best = candidates[0];
                if (!best) return {found: false, samples: candidates.slice(0, 5).map(item => ({text:item.text, score:item.score}))};
                const token = 'ai_article_' + Date.now() + '_' + Math.random().toString(36).slice(2);
                best.el.setAttribute('data-ai-article-action', token);
                return {found: true, selector: '[data-ai-article-action="' + token + '"]', detail: {text: best.text.slice(0, 160), cls: best.cls.slice(0, 180), rect: {x:Math.round(best.r.x), y:Math.round(best.r.y), w:Math.round(best.r.width), h:Math.round(best.r.height)}}};
            }''', {'matcher': matcher})
            _log(self.execution_record, f'BUSINESS_ACTION {intent} scan={scan}')
            if not scan or not scan.get('found'):
                return _fail(f'未找到文章区域的{intent}控件', {'scan': scan})
            locator = self.page.locator(scan['selector'])
            try:
                await locator.click(timeout=1800)
            except Exception as click_error:
                _log(self.execution_record, f'BUSINESS_ACTION {intent} locator_click_fallback={str(click_error)[:160]}')
                await self.page.evaluate(
                    '(selector) => { const node = document.querySelector(selector); if (!node) throw new Error("article action target disappeared"); node.click(); }',
                    scan['selector'],
                )
            await asyncio.sleep(0.7)
            evidence = {'scan': scan}
            if success_check:
                state = await self.page.evaluate(success_check)
                evidence['state'] = state
                if not state.get('passed'):
                    return _fail(f'{intent}点击后页面未进入预期状态', evidence)
            return _ok(f'已执行文章{intent}', evidence)
        except Exception as exc:
            return _fail(f'文章{intent}执行失败: {str(exc)[:200]}')

    async def switch_home_banner(self, step) -> ActionResult:
        """Switch to another rendered community-home banner without relying on stale activity names."""
        try:
            scan = await self.page.evaluate(r'''() => {
                const visible = el => { const r=el.getBoundingClientRect(), s=getComputedStyle(el); return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0'; };
                const norm = value => String(value||'').replace(/\s+/g,' ').trim();
                const leaves = Array.from(document.querySelectorAll('a,button,[role="button"],li,div,span')).filter(visible).filter(el => {
                    const text=norm(el.innerText||el.textContent||''); const r=el.getBoundingClientRect();
                    return text && text.length<=60 && r.left>=innerWidth*.70 && r.top>=100 && r.bottom<=Math.min(innerHeight*.52, 500) && r.width>=45 && r.height>=18;
                }).filter(el => !Array.from(el.querySelectorAll('a,button,[role="button"],li,div,span')).some(child => norm(child.innerText||child.textContent||'') === norm(el.innerText||el.textContent||'')));
                const entries=[];
                for(const leaf of leaves) {
                    const text=norm(leaf.innerText||leaf.textContent||'');
                    let owner=leaf;
                    for(let parent=leaf.parentElement,depth=0;parent&&depth<4;parent=parent.parentElement,depth+=1) {
                        if(!visible(parent)) continue;
                        const r=parent.getBoundingClientRect(), cls=String(parent.className||'');
                        if(r.left>=innerWidth*.65&&r.top>=80&&r.bottom<=520&&r.width<=420&&r.height<=110&&(/cursor-pointer|clickable|active|selected|item/i.test(cls)||parent.tagName==='A'||parent.tagName==='BUTTON')) { owner=parent; break; }
                    }
                    const r=owner.getBoundingClientRect(), cls=String(owner.className||'');
                    const active=/active|selected|current|is-active|is-selected/i.test(cls) || /rgba?\(255,\s*255,\s*255/.test(getComputedStyle(owner).backgroundColor||'');
                    entries.push({owner,text,r,cls,active});
                }
                const unique=[...new Map(entries.map(item=>[item.text,item])).values()].sort((a,b)=>a.r.top-b.r.top);
                const target=unique.find(item=>!item.active) || unique[1];
                const heroSources=Array.from(document.querySelectorAll('img')).filter(visible).map(img=>{const r=img.getBoundingClientRect();return {src:img.currentSrc||img.src||'',x:r.x,y:r.y,w:r.width,h:r.height};}).filter(item=>item.x>=innerWidth*.18&&item.x<=innerWidth*.8&&item.y>=70&&item.y<=500&&item.w>=300&&item.h>=120);
                if(!target)return {found:false,samples:unique.map(item=>({text:item.text,active:item.active,cls:item.cls.slice(0,100)}))};
                const token='ai_home_banner_option_'+Date.now()+'_'+Math.random().toString(36).slice(2); target.owner.setAttribute('data-ai-home-banner-option',token);
                return {found:true,selector:'[data-ai-home-banner-option="'+token+'"]',targetText:target.text,before:{heroSources,activeTexts:unique.filter(item=>item.active).map(item=>item.text)}};
            }''')
            _log(self.execution_record, f'BUSINESS_ACTION nn_switch_home_banner scan={scan}')
            if not scan or not scan.get('found'):
                return _fail('未找到可切换的社区首页 Banner 活动项', {'scan': scan or {}})
            await self.page.locator(scan['selector']).click(timeout=5000, force=True)
            for _ in range(24):
                await asyncio.sleep(.25)
                state = await self.page.evaluate(r'''(payload) => {
                    const visible = el => { const r=el.getBoundingClientRect(), s=getComputedStyle(el); return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0'; };
                    const norm = value => String(value||'').replace(/\s+/g,' ').trim();
                    const target=Array.from(document.querySelectorAll('a,button,[role="button"],li,div,span')).filter(visible).find(el=>norm(el.innerText||el.textContent||'')===payload.targetText);
                    const targetCls=String(target?.className||'');
                    const targetActive=/active|selected|current|is-active|is-selected/i.test(targetCls) || /rgba?\(255,\s*255,\s*255/.test(target ? getComputedStyle(target).backgroundColor||'' : '');
                    const heroSources=Array.from(document.querySelectorAll('img')).filter(visible).map(img=>{const r=img.getBoundingClientRect();return img.currentSrc||img.src||'';}).filter(Boolean);
                    const heroChanged=(payload.before.heroSources||[]).some(item=>!heroSources.includes(item.src));
                    return {targetVisible:!!target,targetActive,heroChanged};
                }''', {'targetText': scan['targetText'], 'before': scan['before']})
                if state.get('targetActive') or state.get('heroChanged'):
                    return _ok('已切换至另一项社区首页 Banner 活动', {'scan': scan, 'state': state})
            return _fail('已点击另一项 Banner 活动，但未检测到选中状态或主图变化', {'scan': scan})
        except Exception as exc:
            return _fail(f'切换社区首页 Banner 失败: {str(exc)[:200]}')

    async def open_article_detail(self, step) -> ActionResult:
        """Open one real article card so detail-dependent cases are self-contained."""
        try:
            scan = await self.page.evaluate(r'''() => {
                const visible = el => { const r=el.getBoundingClientRect(), s=getComputedStyle(el); return r.width > 120 && r.height > 28 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0'; };
                const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
                const candidates = Array.from(document.querySelectorAll('[class*="cursor-pointer"],button,a,article,li,div'))
                    .filter(visible).map(el => {
                        const text = norm(el.innerText || el.textContent || '');
                        const cls = String(el.className || ''); const r = el.getBoundingClientRect();
                        let score = 0;
                        if (/cursor-pointer|article|post|feed|content-item/i.test(cls)) score += 1600;
                        // Activity entries can open an external campaign page
                        // without a comment composer. Comment cases need a
                        // normal announcement/guide detail instead.
                        if (/公告|攻略/.test(text)) score += 650;
                        if (/活动/.test(text)) score -= 1800;
                        if (text.length >= 2 && text.length <= 180) score += 500;
                        if (r.left > innerWidth * .25 && r.left < innerWidth * .9) score += 350;
                        if (/发布|内容管理|搜索|战绩|语音房/.test(text)) score -= 1400;
                        return {el,text,cls,r,score};
                    }).filter(item => item.score >= 1500).sort((a,b) => b.score-a.score);
                const best = candidates[0];
                if (!best) return {found:false, samples:candidates.slice(0,5).map(item=>({text:item.text,score:item.score}))};
                const token='ai_article_detail_'+Date.now()+'_'+Math.random().toString(36).slice(2);
                best.el.setAttribute('data-ai-article-detail-target',token);
                return {found:true, selector:'[data-ai-article-detail-target="'+token+'"]', detail:{text:best.text.slice(0,160),cls:best.cls.slice(0,160)}};
            }''')
            _log(self.execution_record, f'BUSINESS_ACTION nn_open_article_detail scan={scan}')
            if not scan or not scan.get('found'):
                return _fail('未找到可打开的文章卡片', {'scan': scan})
            await self.page.locator(scan['selector']).click(timeout=8000)
            await asyncio.sleep(0.8)
            state = await self.page.evaluate(r'''() => {
                const text = String(document.body?.innerText || '');
                return {passed: /评论|分享|点赞/.test(text), signals: ['评论','分享','点赞'].filter(item => text.includes(item))};
            }''')
            if not state.get('passed'):
                return _fail('文章卡片点击后未检测到详情互动区', {'scan': scan, 'state': state})
            return _ok('已打开文章详情', {'scan': scan, 'state': state})
        except Exception as exc:
            return _fail(f'打开文章详情失败: {str(exc)[:200]}')

    async def close_article_detail(self, step) -> ActionResult:
        try:
            scan = await self.page.evaluate(r'''() => {
                const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
                const detail=Array.from(document.querySelectorAll('[role="dialog"],[aria-modal="true"],[class*="modal" i],[class*="detail" i]')).filter(visible).filter(el => /理性发言，友善互动|评论/.test(String(el.innerText||el.textContent||''))).sort((a,b) => b.getBoundingClientRect().width*b.getBoundingClientRect().height-a.getBoundingClientRect().width*a.getBoundingClientRect().height)[0];
                const root=detail || document.body;
                const rr=root.getBoundingClientRect();
                const candidates=Array.from(root.querySelectorAll('button,[role="button"],a,div,span')).filter(visible).map(el => {
                    const r=el.getBoundingClientRect(); const text=String(el.innerText||el.textContent||el.getAttribute('aria-label')||'').replace(/\s+/g,'').trim();
                    const cls=String(el.className||'')+' '+String(el.getAttribute('aria-label')||'');
                    let score=0;
                    if(/^(关闭|close|×|✕|✖)$/.test(text)||/close/i.test(cls)) score+=5000;
                    if(r.right >= rr.right-90 && r.top <= rr.top+100) score+=1800;
                    if(r.width>=20&&r.width<=80&&r.height>=20&&r.height<=80) score+=600;
                    if(/icon|close|cancel/i.test(cls)) score+=800;
                    return {el,r,text,cls,score};
                }).filter(item=>item.score>=2300).sort((a,b)=>b.score-a.score);
                const best=candidates[0];
                if(!best)return {found:false,samples:candidates.slice(0,5).map(item=>({text:item.text,cls:item.cls,score:item.score}))};
                const token='ai_article_detail_close_'+Date.now(); best.el.setAttribute('data-ai-article-detail-close',token);
                return {found:true,selector:'[data-ai-article-detail-close="'+token+'"]',detail:{text:best.text,cls:best.cls.slice(0,180),rect:{x:Math.round(best.r.x),y:Math.round(best.r.y),w:Math.round(best.r.width),h:Math.round(best.r.height)}}};
            }''')
            _log(self.execution_record, f'BUSINESS_ACTION nn_close_article_detail scan={scan}')
            if not scan or not scan.get('found'):
                return _fail('未找到文章详情关闭控件', {'scan': scan})
            try:
                await self.page.locator(scan['selector']).click(timeout=3000, force=True)
            except Exception as click_error:
                _log(self.execution_record, f'BUSINESS_ACTION nn_close_article_detail locator_click_fallback={str(click_error)[:160]}')
                await self.page.evaluate(
                    '(selector) => { const node=document.querySelector(selector); if(!node) throw new Error("detail close target disappeared"); node.click(); }',
                    scan['selector'],
                )
            rect = ((scan.get('detail') or {}).get('rect') or {})
            try:
                await self.page.mouse.click(
                    float(rect.get('x', 0)) + float(rect.get('w', 0)) / 2,
                    float(rect.get('y', 0)) + float(rect.get('h', 0)) / 2,
                )
            except Exception as mouse_error:
                _log(self.execution_record, f'BUSINESS_ACTION nn_close_article_detail mouse_fallback={str(mouse_error)[:120]}')
            await asyncio.sleep(0.5)
            state=await self.page.evaluate(r'''() => {
                const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
                const roots=Array.from(document.querySelectorAll('[role="dialog"],[aria-modal="true"],[class*="modal" i],[class*="detail" i]')).filter(visible);
                const detailOpen=roots.some(el => /理性发言，友善互动|评论/.test(String(el.innerText||el.textContent||'')) && el.getBoundingClientRect().width>innerWidth*.45);
                return {passed:!detailOpen,detailOpen,rootCount:roots.length};
            }''')
            if not state.get('passed'):
                try:
                    await self.page.keyboard.press('Escape')
                    await asyncio.sleep(0.3)
                    state=await self.page.evaluate(r'''() => {
                        const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
                        const roots=Array.from(document.querySelectorAll('[role="dialog"],[aria-modal="true"],[class*="modal" i],[class*="detail" i]')).filter(visible);
                        const detailOpen=roots.some(el => /理性发言，友善互动|评论/.test(String(el.innerText||el.textContent||'')) && el.getBoundingClientRect().width>innerWidth*.45);
                        return {passed:!detailOpen,detailOpen,rootCount:roots.length};
                    }''')
                except Exception as keyboard_error:
                    _log(self.execution_record, f'BUSINESS_ACTION nn_close_article_detail escape_fallback={str(keyboard_error)[:120]}')
            if not state.get('passed'):
                return _fail('文章详情关闭后评论输入区仍可见', {'scan': scan, 'state': state})
            return _ok('已关闭文章详情', {'scan': scan, 'state': state})
        except Exception as exc:
            return _fail(f'关闭文章详情失败: {str(exc)[:200]}')

    async def _find_article_comment_input(self) -> Dict[str, Any]:
        return await self.page.evaluate(r'''() => {
            const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
            const norm=value => String(value||'').replace(/\s+/g,' ').trim();
            const controls=Array.from(document.querySelectorAll('textarea,input,[contenteditable="true"],[role="textbox"]')).filter(visible);
            const candidates=controls.map(el => {
                const info=norm([el.getAttribute('placeholder'),el.getAttribute('aria-label'),el.getAttribute('name'),el.className,el.parentElement?.innerText].join(' '));
                let score=0;
                if(/理性发言，友善互动/.test(info))score+=4200;
                if(/评论|comment/.test(info))score+=2400;
                if(el.isContentEditable)score+=1000;
                if(el.tagName==='TEXTAREA')score+=700;
                return {el,info,score};
            }).filter(item=>item.score>0).sort((a,b)=>b.score-a.score);
            const best=candidates[0];
            if(!best)return {found:false,samples:controls.slice(0,8).map(el=>({tag:el.tagName,placeholder:el.getAttribute('placeholder'),aria:el.getAttribute('aria-label'),cls:String(el.className||'').slice(0,100)}))};
            const token='ai_article_comment_'+Date.now()+'_'+Math.random().toString(36).slice(2); best.el.setAttribute('data-ai-article-comment',token);
            return {found:true,selector:'[data-ai-article-comment="'+token+'"]',detail:{tag:best.el.tagName,info:best.info.slice(0,180),score:best.score}};
        }''')

    async def _find_article_comment_entry(self) -> Dict[str, Any]:
        return await self.page.evaluate(r'''() => {
            const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
            const norm=value => String(value||'').replace(/\s+/g,' ').trim();
            const labels=Array.from(document.querySelectorAll('div,span,p,label')).filter(visible).filter(el => norm(el.innerText||el.textContent||'') === '理性发言，友善互动');
            const candidates=[];
            for(const label of labels){
                for(let el=label,depth=0;el&&depth<5;el=el.parentElement,depth+=1){
                    if(!visible(el))continue;
                    const r=el.getBoundingClientRect(); const cls=String(el.className||'');
                    let score=0;
                    if(/input|comment|editor|textarea|textbox/i.test(cls))score+=1800;
                    if(r.width>=180&&r.width<=1000&&r.height>=28&&r.height<=160)score+=900;
                    if(r.left>innerWidth*.2&&r.left<innerWidth*.9)score+=500;
                    candidates.push({el,r,cls,score});
                }
            }
            candidates.sort((a,b)=>b.score-a.score);
            const best=candidates[0];
            if(!best)return {found:false,labelCount:labels.length};
            const token='ai_article_comment_entry_'+Date.now(); best.el.setAttribute('data-ai-article-comment-entry',token);
            return {found:true,selector:'[data-ai-article-comment-entry="'+token+'"]',detail:{cls:best.cls.slice(0,180),rect:{x:Math.round(best.r.x),y:Math.round(best.r.y),w:Math.round(best.r.width),h:Math.round(best.r.height)}}};
        }''')

    async def focus_article_comment(self, step) -> ActionResult:
        try:
            scan=await self._find_article_comment_input()
            _log(self.execution_record, f'BUSINESS_ACTION nn_focus_article_comment scan={scan}')
            if scan and scan.get('found'):
                await self.page.locator(scan['selector']).click(timeout=5000)
                return _ok('已聚焦文章评论输入框', {'scan': scan})
            entry=await self._find_article_comment_entry()
            _log(self.execution_record, f'BUSINESS_ACTION nn_focus_article_comment entry={entry}')
            if not entry or not entry.get('found'):
                return _fail('未找到文章详情评论输入入口', {'scan': scan, 'entry': entry})
            try:
                await self.page.locator(entry['selector']).click(timeout=1800)
            except Exception:
                await self.page.evaluate(
                    '(selector) => { const node=document.querySelector(selector); if(!node) throw new Error("comment entry disappeared"); node.click(); }',
                    entry['selector'],
                )
            deadline=time.monotonic()+2.5
            activated={}
            while time.monotonic()<deadline:
                activated=await self._find_article_comment_input()
                if activated and activated.get('found'):
                    break
                await asyncio.sleep(0.2)
            if not activated or not activated.get('found'):
                return _fail('点击评论输入入口后未出现可编辑控件', {'entry':entry,'scan':activated})
            return _ok('已聚焦文章评论输入框', {'entry': entry, 'scan': activated})
        except Exception as exc:
            return _fail(f'聚焦文章评论输入框失败: {str(exc)[:200]}')

    async def fill_article_comment(self, step) -> ActionResult:
        value=str(step.get('input_value') or '').strip()
        if not value:
            return _fail('文章评论缺少输入值')
        try:
            scan=await self._find_article_comment_input()
            _log(self.execution_record, f'BUSINESS_ACTION nn_fill_article_comment scan={scan}')
            if not scan or not scan.get('found'):
                return _fail('未找到文章详情评论输入框', {'scan': scan})
            locator=self.page.locator(scan['selector'])
            await _fill_and_verify(locator, value)
            actual=await locator.evaluate(r'''el => String(el.isContentEditable ? (el.innerText||el.textContent||'') : (el.value||''))''')
            if value not in actual:
                return _fail('文章评论写入后读取值不一致', {'scan':scan,'expected':value,'actual':actual[:300]})
            return _ok('已输入文章评论', {'scan':scan,'value':value})
        except Exception as exc:
            return _fail(f'输入文章评论失败: {str(exc)[:200]}')

    async def open_article_management(self, step) -> ActionResult:
        try:
            state = await self._article_management_state()
            if not state.get('open'):
                # Saving a draft leaves NN's full-screen editor open.  The
                # management entry is not rendered behind that editor, so
                # close it first instead of searching the whole document for
                # a control that cannot currently be reached.
                editor = await self._article_editor_state()
                if editor.get('open'):
                    closed = await self.close_article_editor({})
                    if closed.get('status') != 'completed':
                        return _fail('打开内容管理前无法关闭文章编辑器', {
                            'editor': editor,
                            'close': closed,
                        })
                    state = await self._article_management_state()
                result = await self._click_article_candidate(
                    '内容管理',
                    r'^内容管理$',
                    r'''() => { const text=String(document.body?.innerText || ''); return {passed:/发布中|草稿箱|已下架/.test(text)}; }''',
                )
                if result.get('status') != 'completed':
                    return result
            else:
                result = _ok('文章内容管理已打开', {'management_state': state})

            # The NN site keeps the editor open after a successful draft save.
            # A click or toast is therefore only a submission acknowledgement;
            # the authoritative result is that this run's title exists in the
            # draft tab and is absent from the published tab.
            context = await self._article_runtime_context()
            if context.get('pending_draft') or step.get('article_tab') == 'draft':
                verified = await self._verify_article_draft_present()
                if verified.get('status') != 'completed':
                    return verified
                evidence = dict(result.get('element') or {})
                evidence['draft_verification'] = verified.get('element') or {}
                return _ok('已打开内容管理并验证本次草稿', evidence)
            return result
        except Exception as exc:
            return _fail(f'打开文章内容管理失败: {str(exc)[:200]}')

    async def _article_runtime_context(self) -> Dict[str, str]:
        return await self.page.evaluate(r'''() => {
            const root=document.documentElement;
            return {
                title: root.getAttribute('data-ai-article-title') || '',
                previous_title: root.getAttribute('data-ai-article-previous-title') || '',
                body: root.getAttribute('data-ai-article-body') || '',
                storage: root.getAttribute('data-ai-article-storage') || '',
                pending_draft: root.getAttribute('data-ai-article-pending-draft') === 'true',
            };
        }''')

    async def _article_management_state(self) -> Dict[str, Any]:
        return await self.page.evaluate(r'''() => {
            const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0'; };
            const roots=Array.from(document.querySelectorAll('[role="dialog"],[aria-modal="true"],[class*="modal" i],[class*="dialog" i]')).filter(visible);
            const root=roots.find(el => /发布中|草稿箱|已下架/.test(String(el.innerText||el.textContent||'')));
            return {open:!!root, rootText:root ? String(root.innerText||root.textContent||'').slice(0,800) : ''};
        }''')

    async def _article_editor_state(self) -> Dict[str, Any]:
        """Detect the publish editor without confusing normal page inputs for it."""
        return await self.page.evaluate(r'''() => {
            const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
            const text=String(document.body?.innerText || '');
            const fields=Array.from(document.querySelectorAll('input,textarea,[contenteditable="true"]')).filter(visible);
            const hasBodyEditor=fields.some(el => el.isContentEditable || el.tagName==='TEXTAREA');
            // wangEditor used by NN can expose its editable surface through
            // a non-contenteditable wrapper, so field-only detection misses
            // the full-screen article editor.
            const editorWidgets=Array.from(document.querySelectorAll('[class*="w-e-"],[class*="editor" i],[class*="publish" i]')).filter(visible);
            // Article titles on the normal feed can contain words such as
            // "活动发布". The editor is authoritative only while its dedicated
            // save-draft action is visible alongside an editable surface.
            const hasDraftAction=Array.from(document.querySelectorAll('button,[role="button"],a,div,span')).filter(visible)
                .some(el => /^(?:存草稿|保存草稿)$/.test(String(el.innerText||el.textContent||'').replace(/\s+/g,'')));
            const editorPage=hasDraftAction && /(?:发布设置|存草稿|公告发布|活动发布|攻略发布)/.test(text);
            return {
                open: editorPage && (hasBodyEditor || editorWidgets.length > 0),
                fieldCount: fields.length,
                hasBodyEditor,
                editorWidgetCount: editorWidgets.length,
                editorPage,
            };
        }''')

    async def _select_article_management_tab(self, label: str) -> ActionResult:
        try:
            scan = await self.page.evaluate(r'''(label) => {
                const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0'; };
                const norm=value => String(value||'').replace(/\s+/g,' ').trim();
                const roots=Array.from(document.querySelectorAll('[role="dialog"],[aria-modal="true"],[class*="modal" i],[class*="dialog" i]')).filter(visible);
                const root=roots.find(el => /发布中|草稿箱|已下架/.test(norm(el.innerText||el.textContent||'')));
                if(!root)return {found:false,reason:'内容管理弹窗未打开'};
                const candidates=Array.from(root.querySelectorAll('button,[role="button"],a,[class*="cursor-pointer" i],div,span')).filter(visible).map(source => {
                    const text=norm(source.innerText||source.textContent||'');
                    const compact=text.replace(/\s+/g,'');
                    if(compact!==label && !compact.startsWith(label+'('))return null;
                    const direct=source.closest('button,[role="button"],a,[class*="cursor-pointer" i],[class*="clickable" i]');
                    const el=(direct && root.contains(direct)) ? direct : source;
                    const r=el.getBoundingClientRect();
                    if(r.width>240 || r.height>90)return null;
                    return {el,r,score:(el.tagName==='BUTTON'?1000:0)+(/tab|cursor-pointer|active/i.test(String(el.className||''))?500:0)};
                }).filter(Boolean).sort((a,b)=>b.score-a.score);
                const best=candidates[0];
                if(!best)return {found:false,reason:'未找到管理标签 '+label};
                const token='ai_article_management_tab_'+Date.now()+'_'+Math.random().toString(36).slice(2);
                best.el.setAttribute('data-ai-article-management-tab',token);
                return {found:true,selector:'[data-ai-article-management-tab="'+token+'"]'};
            }''', label)
            if not scan.get('found'):
                return _fail('未找到文章管理标签', {'scan': scan, 'label': label})
            await self.page.locator(scan['selector']).click(timeout=5000)
            await asyncio.sleep(0.5)
            return _ok(f'已切换文章管理标签「{label}」', {'scan': scan})
        except Exception as exc:
            return _fail(f'切换文章管理标签失败: {str(exc)[:200]}')

    async def _find_runtime_article_row(self, title: str, require_present=True) -> ActionResult:
        try:
            scan = await self.page.evaluate(r'''(payload) => {
                const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0'; };
                const norm=value => String(value||'').replace(/\s+/g,' ').trim();
                const roots=Array.from(document.querySelectorAll('[role="dialog"],[aria-modal="true"],[class*="modal" i],[class*="dialog" i]')).filter(visible);
                const root=roots.find(el => /发布中|草稿箱|已下架/.test(norm(el.innerText||el.textContent||'')));
                if(!root)return {found:false,reason:'内容管理弹窗未打开'};
                const rootRect=root.getBoundingClientRect();
                const visibleInManagementList=el => {
                    if(!visible(el))return false;
                    const r=el.getBoundingClientRect();
                    // Virtualized rows can remain mounted after a deletion.
                    // Only a row rendered inside the dialog's visible area is
                    // evidence that the user can still query the article.
                    return r.bottom>rootRect.top && r.top<rootRect.bottom && r.bottom>0 && r.top<innerHeight;
                };
                const matches=Array.from(root.querySelectorAll('div,article,li,a,span,p,h1,h2,h3')).filter(visibleInManagementList).filter(el => norm(el.innerText||el.textContent||'')===payload.title);
                const source=matches.sort((a,b)=>a.getBoundingClientRect().width-b.getBoundingClientRect().width)[0];
                if(!source)return {found:false,reason:'当前标签未找到运行时标题',title:payload.title,rootText:norm(root.innerText||root.textContent||'').slice(0,900)};
                let row=source;
                for(let depth=0; row && depth<8; depth+=1,row=row.parentElement){
                    const text=norm(row.innerText||row.textContent||''); const r=row.getBoundingClientRect();
                    if(r.width>=300 && r.width<=1000 && r.height>=36 && r.height<=180 && text.includes(payload.title)){break;}
                }
                if(!row)row=source;
                const token='ai_article_runtime_row_'+Date.now()+'_'+Math.random().toString(36).slice(2);
                row.setAttribute('data-ai-article-runtime-row',token);
                const text=norm(row.innerText||row.textContent||'');
                return {found:true,selector:'[data-ai-article-runtime-row="'+token+'"]',detail:{text:text.slice(0,500),hasEdit:/编辑/.test(text),hasDelete:/删除/.test(text)}};
            }''', {'title': title, 'require_present': require_present})
            if not scan.get('found'):
                return _fail('未在文章管理中找到本次运行标题', {'scan': scan, 'title': title})
            return _ok('已定位本次运行文章', {'scan': scan, 'title': title})
        except Exception as exc:
            return _fail(f'定位本次运行文章失败: {str(exc)[:200]}')

    async def _open_article_row_menu(self, row_selector: str) -> ActionResult:
        try:
            scan = await self.page.locator(row_selector).evaluate(r'''row => {
                const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0'; };
                const norm=value => String(value||'').replace(/\s+/g,'').trim();
                const rowRect=row.getBoundingClientRect();
                const nodes=Array.from(row.querySelectorAll('button,[role="button"],a,[class*="cursor-pointer" i],[class*="more" i],svg,i,span,div')).filter(visible);
                const candidates=nodes.map(el => {
                    const r=el.getBoundingClientRect(); const text=norm(el.innerText||el.textContent||el.getAttribute('aria-label')||'');
                    const cls=String(el.className||'')+' '+String(el.getAttribute('aria-label')||'');
                    let score=0;
                    if(/^(?:\.\.\.|…)$/.test(text))score+=5000;
                    if(/more|更多|操作|ellipsis/i.test(cls))score+=2500;
                    if(r.left>=rowRect.right-100 && r.width<=72 && r.height<=56)score+=900;
                    if(el.tagName==='BUTTON'||el.getAttribute('role')==='button'||/cursor-pointer|clickable/i.test(cls))score+=700;
                    if(r.left<rowRect.right-130)score-=2000;
                    return {el,r,text,cls,score};
                }).filter(item=>item.score>=1500).sort((a,b)=>b.score-a.score);
                const best=candidates[0];
                if(!best)return {found:false,rowText:String(row.innerText||row.textContent||'').slice(0,500),samples:candidates.slice(0,5).map(item=>({text:item.text,cls:item.cls,score:item.score}))};
                const token='ai_article_row_menu_'+Date.now(); best.el.setAttribute('data-ai-article-row-menu',token); return {found:true,selector:'[data-ai-article-row-menu="'+token+'"]',detail:{text:best.text,cls:best.cls.slice(0,180),rect:{x:Math.round(best.r.x),y:Math.round(best.r.y),w:Math.round(best.r.width),h:Math.round(best.r.height)}}};
            }''')
            if not scan.get('found'):
                return _fail('未找到草稿条目的更多操作菜单', {'scan': scan})
            await self.page.locator(scan['selector']).click(timeout=5000)
            await asyncio.sleep(0.35)
            return _ok('已打开草稿条目更多操作菜单', {'scan': scan})
        except Exception as exc:
            return _fail(f'打开草稿条目操作菜单失败: {str(exc)[:200]}')

    async def _click_article_row_menu_operation(self, operation: str) -> ActionResult:
        try:
            scan = await self.page.evaluate(r'''(operation) => {
                const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0'; };
                const norm=value => String(value||'').replace(/\s+/g,'').trim();
                const all=Array.from(document.querySelectorAll('button,[role="button"],a,div,span,li')).filter(visible);
                const candidates=all.map(source => {
                    const text=norm(source.innerText||source.textContent||source.getAttribute('aria-label')||'');
                    if(text!==operation)return null;
                    const el=source.closest('button,[role="button"],a,[class*="cursor-pointer" i],[class*="clickable" i]') || source;
                    const cls=String(el.className||'')+' '+String(source.className||'');
                    const r=el.getBoundingClientRect();
                    let score=(el.tagName==='BUTTON'||el.getAttribute('role')==='button'?1000:0)+(/menu|dropdown|popover|cursor-pointer|clickable/i.test(cls)?1000:0);
                    let parent=el.parentElement;
                    for(let depth=0; parent&&depth<5;depth+=1,parent=parent.parentElement){if(/menu|dropdown|popover/i.test(String(parent.className||''))){score+=1800;break;}}
                    if(r.width<=260&&r.height<=80)score+=300;
                    return {el,cls,r,score};
                }).filter(Boolean).sort((a,b)=>b.score-a.score);
                const best=candidates[0]; if(!best)return {found:false,operation,samples:[]};
                const token='ai_article_row_operation_'+Date.now(); best.el.setAttribute('data-ai-article-row-operation',token); return {found:true,selector:'[data-ai-article-row-operation="'+token+'"]',detail:{cls:best.cls.slice(0,180),rect:{x:Math.round(best.r.x),y:Math.round(best.r.y),w:Math.round(best.r.width),h:Math.round(best.r.height)}}};
            }''', operation)
            if not scan.get('found'):
                return _fail(f'更多操作菜单中未找到「{operation}」', {'scan': scan})
            await self.page.locator(scan['selector']).click(timeout=5000)
            await asyncio.sleep(0.45)
            return _ok(f'已在草稿操作菜单点击「{operation}」', {'scan': scan})
        except Exception as exc:
            return _fail(f'点击草稿菜单操作失败: {str(exc)[:200]}')

    async def _verify_article_draft_present(self) -> ActionResult:
        context = await self._article_runtime_context()
        title = context.get('title', '').strip()
        if not title:
            return _fail('草稿校验缺少本次运行标题')
        _log(self.execution_record, f'BUSINESS_ACTION article_draft_context title={title!r} previous_title={context.get("previous_title", "")!r}')
        state = await self._article_management_state()
        if not state.get('open'):
            opened = await self._click_article_candidate(
                '内容管理',
                r'^内容管理$',
                r'''() => { const text=String(document.body?.innerText || ''); return {passed:/发布中|草稿箱|已下架/.test(text)}; }''',
            )
            if opened.get('status') != 'completed':
                return opened
        tab = await self._select_article_management_tab('草稿箱')
        if tab.get('status') != 'completed':
            return tab
        found = await self._find_runtime_article_row(title)
        if found.get('status') != 'completed':
            return found
        previous_title = context.get('previous_title', '').strip()
        if previous_title and previous_title != title:
            old_row = await self._find_runtime_article_row(previous_title)
            if old_row.get('status') == 'completed':
                return _fail('编辑保存后原标题仍作为独立草稿存在', {'title': title, 'previous_title': previous_title, 'old_row': old_row.get('element')})
        published = await self._select_article_management_tab('发布中')
        if published.get('status') != 'completed':
            return published
        published_row = await self._find_runtime_article_row(title)
        if published_row.get('status') == 'completed':
            return _fail('本次草稿错误出现在发布中', {'title': title, 'published_row': published_row.get('element')})
        await self._select_article_management_tab('草稿箱')
        await self.page.evaluate(r'''() => {
            const root=document.documentElement;
            root.setAttribute('data-ai-article-storage','draft');
            root.removeAttribute('data-ai-article-pending-draft');
        }''')
        return _ok('已在草稿箱验证本次草稿且未发布', {'title': title, 'draft_row': found.get('element')})

    async def _verify_article_published_present(self) -> ActionResult:
        context = await self._article_runtime_context()
        title = context.get('title', '').strip()
        if not title:
            return _fail('发布文章校验缺少本次运行标题')
        state = await self._article_management_state()
        if not state.get('open'):
            opened = await self._click_article_candidate('内容管理', r'^内容管理$', r'''() => { const text=String(document.body?.innerText || ''); return {passed:/发布中|草稿箱|已下架/.test(text)}; }''')
            if opened.get('status') != 'completed':
                return opened
        tab = await self._select_article_management_tab('发布中')
        if tab.get('status') != 'completed':
            return tab
        found = await self._find_runtime_article_row(title)
        if found.get('status') != 'completed':
            return _fail('未在发布中找到本次运行文章', {'title': title, 'lookup': found.get('element')})
        draft = await self._select_article_management_tab('草稿箱')
        if draft.get('status') != 'completed':
            return draft
        draft_row = await self._find_runtime_article_row(title)
        if draft_row.get('status') == 'completed':
            return _fail('发布后文章仍残留在草稿箱', {'title': title, 'draft_row': draft_row.get('element')})
        await self._select_article_management_tab('发布中')
        await self.page.evaluate(r'''() => {
            const root=document.documentElement;
            root.setAttribute('data-ai-article-storage','published');
            root.removeAttribute('data-ai-article-pending-draft');
        }''')
        return _ok('已在发布中验证本次文章且草稿已清除', {'title': title, 'published_row': found.get('element')})

    async def open_article_published_for_edit(self, step) -> ActionResult:
        verified = await self._verify_article_published_present()
        if verified.get('status') != 'completed':
            return verified
        context = await self._article_runtime_context()
        found = await self._find_runtime_article_row(context['title'])
        if found.get('status') != 'completed':
            return found
        menu = await self._open_article_row_menu(found['element']['scan']['selector'])
        if menu.get('status') != 'completed':
            return menu
        operation = await self._click_article_row_menu_operation('编辑')
        if operation.get('status') != 'completed':
            return operation
        editor = await self.page.evaluate(r'''(title) => {
            const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
            const fields=Array.from(document.querySelectorAll('input,textarea,[contenteditable="true"]')).filter(visible);
            const values=fields.map(el=>String(el.isContentEditable?(el.innerText||el.textContent||''):(el.value||'')));
            return {open:fields.length>0,titleRestored:values.some(value=>value.includes(title))};
        }''', context['title'])
        if not editor.get('open') or not editor.get('titleRestored'):
            return _fail('打开已发布文章编辑器后未回填本次标题', {'editor': editor, 'title': context['title']})
        return _ok('已打开并验证已发布文章编辑器回填', {'edit': operation.get('element'), 'editor': editor})

    async def delete_published_article(self, step) -> ActionResult:
        verified = await self._verify_article_published_present()
        if verified.get('status') != 'completed':
            return verified
        context = await self._article_runtime_context()
        found = await self._find_runtime_article_row(context['title'])
        if found.get('status') != 'completed':
            return found
        menu = await self._open_article_row_menu(found['element']['scan']['selector'])
        if menu.get('status') != 'completed':
            return menu
        operation = await self._click_article_row_menu_operation('删除')
        if operation.get('status') != 'completed':
            return operation
        dialog = await self.page.evaluate(r'''() => { const text=String(document.body?.innerText||''); return {open:/删除|确认/.test(text),text:text.slice(-500)}; }''')
        if not dialog.get('open'):
            return _fail('点击发布中文章删除后未出现确认弹窗', {'operation': operation.get('element'), 'dialog': dialog})
        return _ok('已打开已发布文章删除确认弹窗', {'operation': operation.get('element'), 'dialog': dialog})

    async def delete_all_current_user_published_articles(self, step) -> ActionResult:
        """Delete every remaining row in the account-scoped published list."""
        state = await self._article_management_state()
        if not state.get('open'):
            opened = await self._click_article_candidate(
                '内容管理',
                r'^内容管理$',
                r'''() => { const text=String(document.body?.innerText || ''); return {passed:/发布中|草稿箱|已下架/.test(text)}; }''',
            )
            if opened.get('status') != 'completed':
                return opened

        tab = await self._select_article_management_tab('发布中')
        if tab.get('status') != 'completed':
            return tab

        async def next_row():
            return await self.page.evaluate(r'''() => {
                const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0'; };
                const onScreen=el => {
                    if(!visible(el))return false;
                    const r=el.getBoundingClientRect();
                    return r.bottom>0 && r.right>0 && r.top<innerHeight && r.left<innerWidth;
                };
                const norm=value => String(value||'').replace(/\s+/g,' ').trim();
                // vue-recycle-scroller keeps prior rows (and sometimes a
                // previous modal tree) mounted far outside the viewport.
                // Geometry alone is not visibility; only the current dialog
                // and its on-screen controls are valid interaction targets.
                const roots=Array.from(document.querySelectorAll('[role="dialog"],[aria-modal="true"],[class*="modal" i],[class*="dialog" i]')).filter(onScreen);
                const root=roots.find(el => /发布中|草稿箱|已下架/.test(String(el.innerText||el.textContent||'')));
                if(!root)return {found:false,reason:'内容管理弹窗未打开'};
                const rootRect=root.getBoundingClientRect();
                const rowFor=trigger => {
                    for(let row=trigger.parentElement,depth=0;row&&depth<10;depth+=1,row=row.parentElement){
                        const r=row.getBoundingClientRect();
                        const text=norm(row.innerText||row.textContent||'');
                        if(
                            root.contains(row) && r.width>=300 && r.width<=1000 &&
                            r.height>=36 && r.height<=180 && r.top>=rootRect.top+90 &&
                            r.bottom<=rootRect.bottom && text.length>0
                        ) return row;
                    }
                    return null;
                };
                const triggerFor=source => {
                    let signal=null;
                    let activation=null;
                    for(let el=source,depth=0;el&&depth<7&&el!==root;depth+=1,el=el.parentElement){
                        if(!visible(el))continue;
                        const r=el.getBoundingClientRect();
                        if(r.width<=0||r.height<=0||r.width>96||r.height>64)continue;
                        const text=norm(el.innerText||el.textContent||el.getAttribute('aria-label')||'').replace(/\s+/g,'');
                        const cls=String(el.className||'')+' '+String(el.getAttribute('aria-label')||'');
                        let score=0;
                        if(/^(?:\.\.\.|…|更多|操作)$/.test(text))score+=5000;
                        if(/more|ellipsis|three[-_ ]?dot|操作/i.test(cls))score+=2600;
                        if(/button|cursor-pointer|clickable/i.test(cls)||el.tagName==='BUTTON'||el.getAttribute('role')==='button')score+=900;
                        // The menu icon itself can be an unlabeled SVG.  Its
                        // placement at the row's far right is still useful
                        // evidence, but only after a real article row exists.
                        if(r.width<=40&&r.height<=40)score+=250;
                        if(!signal||score>signal.score)signal={el,r,text,cls,score};
                        // The visual three-dot glyph is often an <i> with
                        // pointer-events disabled.  Keep walking until the
                        // enclosing button/clickable element is found, then
                        // use that element as the Playwright click target.
                        if(/button|cursor-pointer|clickable/i.test(cls)||el.tagName==='BUTTON'||el.getAttribute('role')==='button'){
                            activation={el,r,text,cls,score};
                        }
                    }
                    if(signal&&activation){
                        return {
                            ...activation,
                            text: signal.text || activation.text,
                            cls: String(activation.cls||'')+' '+String(signal.cls||''),
                            score: Math.max(signal.score, activation.score)+900,
                        };
                    }
                    return signal;
                };
                const controls=Array.from(root.querySelectorAll('button,[role="button"],a,svg,i,span,div')).filter(onScreen);
                const candidates=[];
                for(const source of controls){
                    const trigger=triggerFor(source);
                    if(!trigger)continue;
                    const row=rowFor(trigger.el);
                    if(!row)continue;
                    const rowRect=row.getBoundingClientRect();
                    if(trigger.r.left<rowRect.right-140)continue;
                    // Avoid treating decorative status icons as an article menu.
                    if(trigger.score<900)continue;
                    candidates.push({row,trigger,score:trigger.score,rowText:norm(row.innerText||row.textContent||'')});
                }
                candidates.sort((a,b)=>b.score-a.score);
                const best=candidates[0];
                if(!best){
                    const empty=/暂无|没有.*文章|空空如也/.test(norm(root.innerText||root.textContent||''));
                    return {found:false,empty,reason:empty?'发布中列表已为空':'发布中列表没有可删除的文章条目'};
                }
                const token='ai_article_published_cleanup_menu_'+Date.now()+'_'+Math.random().toString(36).slice(2);
                best.trigger.el.setAttribute('data-ai-article-published-cleanup-menu',token);
                const triggerChain=[];
                for(let el=best.trigger.el,depth=0;el&&depth<5&&el!==root;depth+=1,el=el.parentElement){
                    const r=el.getBoundingClientRect();
                    triggerChain.push({tag:el.tagName,cls:String(el.className||'').slice(0,220),rect:{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)}});
                }
                return {found:true,menu_selector:'[data-ai-article-published-cleanup-menu="'+token+'"]',detail:{text:best.rowText.slice(0,500),menuText:best.trigger.text,menuClass:best.trigger.cls.slice(0,160),triggerChain}};
            }''')

        deleted_rows = []
        for _ in range(50):
            row = await next_row()
            if not row.get('found'):
                if row.get('empty'):
                    return _ok('已删除发布中列表内当前账号的全部文章', {'deleted_count': len(deleted_rows), 'deleted_rows': deleted_rows})
                return _fail('发布中列表尚未为空，但未找到行级删除菜单；为防止误删已停止', {'scan': row, 'deleted_rows': deleted_rows})

            try:
                await self.page.locator(row['menu_selector']).click(timeout=5000)
                await asyncio.sleep(0.35)
            except Exception as exc:
                # NN renders the three-dot affordance as an icon in some
                # historical rows.  Those icons can have pointer-events:none,
                # while their parent still receives React's bubbled click.
                # Dispatching on the already-scoped icon keeps this fallback
                # on the same account-owned row instead of searching globally.
                try:
                    await self.page.locator(row['menu_selector']).dispatch_event('click')
                    await asyncio.sleep(0.35)
                except Exception as fallback_exc:
                    return _fail(
                        '打开发布中文章操作菜单失败',
                        {
                            'row': row,
                            'error': str(exc)[:200],
                            'fallback_error': str(fallback_exc)[:200],
                            'deleted_rows': deleted_rows,
                        },
                    )
            operation = await self._click_article_row_menu_operation('删除')
            if operation.get('status') != 'completed':
                return _fail('点击发布中文章删除操作失败', {'row': row, 'operation': operation, 'deleted_rows': deleted_rows})
            confirmed = await self.confirm_article_draft_delete({})
            if confirmed.get('status') != 'completed':
                return _fail('确认删除发布中文章失败', {'row': row, 'confirmed': confirmed, 'deleted_rows': deleted_rows})
            deleted_rows.append(row.get('detail', {}).get('text', ''))
            _log(self.execution_record, f'BUSINESS_ACTION published_article_cleanup deleted={len(deleted_rows)} row={deleted_rows[-1][:160]!r}')
            await asyncio.sleep(0.35)
            state = await self._article_management_state()
            if not state.get('open'):
                refreshed = await self._reopen_article_management()
                if refreshed.get('status') != 'completed':
                    return _fail('删除后重新打开发布中列表失败', {'refreshed': refreshed, 'deleted_rows': deleted_rows})
            tab = await self._select_article_management_tab('发布中')
            if tab.get('status') != 'completed':
                return _fail('删除后重新进入发布中列表失败', {'tab': tab, 'deleted_rows': deleted_rows})

        return _fail('发布中文章清理超过安全上限 50 条，已停止', {'deleted_rows': deleted_rows})

    async def verify_published_article_absent(self, step) -> ActionResult:
        context = await self._article_runtime_context()
        title = context.get('title', '').strip()
        if not title:
            return _fail('发布文章删除校验缺少本次运行标题')
        refreshed = await self._reopen_article_management()
        if refreshed.get('status') != 'completed':
            return refreshed
        tab = await self._select_article_management_tab('发布中')
        if tab.get('status') != 'completed':
            return tab
        found = await self._find_runtime_article_row(title)
        if found.get('status') == 'completed':
            return _fail('删除后发布中仍展示本次标题', {'title': title, 'row': found.get('element')})
        return _ok('已验证发布中不再展示本次标题', {'title': title, 'lookup': found.get('element')})

    async def _reopen_article_management(self) -> ActionResult:
        """Reload management data after a destructive operation; tab state alone is stale on NN."""
        try:
            close = await self.page.evaluate(r'''() => {
                const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
                const roots=Array.from(document.querySelectorAll('[role="dialog"],[aria-modal="true"],[class*="modal" i],[class*="dialog" i]')).filter(visible);
                const root=roots.find(el => /发布中|草稿箱|已下架/.test(String(el.innerText||el.textContent||'')));
                if(!root)return {found:false,already_closed:true};
                const rootRect=root.getBoundingClientRect();
                const nodes=Array.from(root.querySelectorAll('button,[role="button"],[aria-label],svg,span,div')).filter(visible);
                const target=nodes.find(el => {
                    const text=String(el.innerText||el.textContent||el.getAttribute('aria-label')||'').replace(/\s+/g,'');
                    const cls=String(el.className||'')+' '+String(el.getAttribute('aria-label')||''); const r=el.getBoundingClientRect();
                    return /^(?:关闭|close|×|✕|✖)$/.test(text) || /close/i.test(cls) || (r.left>=rootRect.right-90 && r.top<=rootRect.top+90 && r.width<=70 && r.height<=70);
                });
                if(!target)return {found:false,reason:'未找到内容管理关闭按钮'};
                const r=target.getBoundingClientRect();
                const token='ai_article_management_refresh_close_'+Date.now(); target.setAttribute('data-ai-article-management-refresh-close',token); return {found:true,selector:'[data-ai-article-management-refresh-close="'+token+'"]',rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
            }''')
            if close.get('found'):
                try:
                    await self.page.locator(close['selector']).click(timeout=1500)
                except Exception:
                    rect = close.get('rect') or {}
                    if not rect:
                        raise
                    await self.page.mouse.click(rect['x'] + rect['w'] / 2, rect['y'] + rect['h'] / 2)
                await asyncio.sleep(0.4)
            elif not close.get('already_closed'):
                return _fail('关闭内容管理以刷新数据失败', {'close': close})
            remaining = await self._article_management_state()
            if remaining.get('open'):
                # Some NN dialog variants deliberately ignore close while the
                # mutation result is being rendered.  The refreshed list is
                # still visible in that same authoritative dialog.
                return _ok('文章内容管理保持打开，继续以当前刷新列表校验', {'close': close, 'state': remaining})
            opened = await self._click_article_candidate(
                '内容管理',
                r'^内容管理$',
                r'''() => { const text=String(document.body?.innerText || ''); return {passed:/发布中|草稿箱|已下架/.test(text)}; }''',
            )
            if opened.get('status') != 'completed':
                return opened
            return _ok('已重新打开文章内容管理并刷新数据', {'close': close, 'opened': opened.get('element')})
        except Exception as exc:
            return _fail(f'刷新文章内容管理失败: {str(exc)[:200]}')

    async def open_article_draft_for_edit(self, step) -> ActionResult:
        verified = await self._verify_article_draft_present()
        if verified.get('status') != 'completed':
            return verified
        context = await self._article_runtime_context()
        found = await self._find_runtime_article_row(context['title'])
        if found.get('status') != 'completed':
            return found
        try:
            menu = await self._open_article_row_menu(found['element']['scan']['selector'])
            if menu.get('status') != 'completed':
                return menu
            operation = await self._click_article_row_menu_operation('编辑')
            if operation.get('status') != 'completed':
                return operation
            await asyncio.sleep(0.4)
            editor = await self.page.evaluate(r'''(title) => {
                const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
                const fields=Array.from(document.querySelectorAll('input,textarea,[contenteditable="true"]')).filter(visible);
                const values=fields.map(el=>String(el.isContentEditable?(el.innerText||el.textContent||''):(el.value||'')));
                return {open:fields.length>0, titleRestored:values.some(value=>value.includes(title)), valueSamples:values.map(value=>value.slice(0,160))};
            }''', context['title'])
            if not editor.get('open') or not editor.get('titleRestored'):
                return _fail('打开草稿编辑器后未回填本次草稿标题', {'editor': editor, 'title': context['title']})
            return _ok('已打开并验证草稿编辑器回填', {'edit': operation.get('element'), 'editor': editor})
        except Exception as exc:
            return _fail(f'打开草稿编辑器失败: {str(exc)[:200]}')

    async def delete_article_draft(self, step) -> ActionResult:
        verified = await self._verify_article_draft_present()
        if verified.get('status') != 'completed':
            return verified
        context = await self._article_runtime_context()
        found = await self._find_runtime_article_row(context['title'])
        if found.get('status') != 'completed':
            return found
        try:
            menu = await self._open_article_row_menu(found['element']['scan']['selector'])
            if menu.get('status') != 'completed':
                return menu
            operation = await self._click_article_row_menu_operation('删除')
            if operation.get('status') != 'completed':
                return operation
            await asyncio.sleep(0.35)
            dialog = await self.page.evaluate(r'''() => {
                const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
                const roots=Array.from(document.querySelectorAll('[role="dialog"],[aria-modal="true"],[class*="modal" i],[class*="dialog" i]')).filter(visible);
                const root=roots.find(el=>/删除|确认/.test(String(el.innerText||el.textContent||'')));
                return {open:!!root,text:root?String(root.innerText||root.textContent||'').slice(0,500):''};
            }''')
            if not dialog.get('open'):
                return _fail('点击删除后未出现删除确认弹窗', {'delete': operation.get('element'), 'dialog': dialog})
            return _ok('已打开草稿删除确认弹窗', {'delete': operation.get('element'), 'dialog': dialog})
        except Exception as exc:
            return _fail(f'打开草稿删除确认失败: {str(exc)[:200]}')

    async def confirm_article_draft_delete(self, step) -> ActionResult:
        try:
            scan = await self.page.evaluate(r'''() => {
                const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
                const roots=Array.from(document.querySelectorAll('[role="dialog"],[aria-modal="true"],[class*="modal" i],[class*="dialog" i]')).filter(visible);
                const root=roots.find(el=>/删除|确认/.test(String(el.innerText||el.textContent||'')));
                if(!root)return {found:false,reason:'删除确认弹窗未打开'};
                const nodes=Array.from(root.querySelectorAll('button,[role="button"]')).filter(visible);
                const target=nodes.find(el=>/^(确认删除|确定删除|确认|确定)$/.test(String(el.innerText||el.textContent||'').replace(/\s+/g,'')));
                if(!target)return {found:false,reason:'删除确认弹窗未找到确认按钮',text:String(root.innerText||root.textContent||'').slice(0,400)};
                const token='ai_article_delete_confirm_'+Date.now(); target.setAttribute('data-ai-article-delete-confirm',token); return {found:true,selector:'[data-ai-article-delete-confirm="'+token+'"]'};
            }''')
            if not scan.get('found'):
                return _fail('未找到草稿删除确认按钮', {'scan': scan})
            await self.page.locator(scan['selector']).click(timeout=5000)
            deadline = time.monotonic() + 4
            state = {}
            while time.monotonic() < deadline:
                state = await self.page.evaluate(r'''() => {
                    const text=String(document.body?.innerText||'');
                    return {success:/删除成功|操作成功/.test(text), dialogOpen:/确认删除|确定删除/.test(text), text:text.slice(-500)};
                }''')
                if state.get('success'):
                    return _ok('已确认删除草稿并收到成功反馈', {'scan': scan, 'state': state})
                await asyncio.sleep(0.25)
            return _fail('确认删除后未收到删除成功反馈', {'scan': scan, 'state': state})
        except Exception as exc:
            return _fail(f'确认删除草稿失败: {str(exc)[:200]}')

    async def verify_article_draft_absent(self, step) -> ActionResult:
        context = await self._article_runtime_context()
        title = context.get('title', '').strip()
        if not title:
            return _fail('删除校验缺少本次运行标题')
        refreshed = await self._reopen_article_management()
        if refreshed.get('status') != 'completed':
            return refreshed
        tab = await self._select_article_management_tab('草稿箱')
        if tab.get('status') != 'completed':
            return tab
        await asyncio.sleep(0.5)
        found = await self._find_runtime_article_row(title)
        if found.get('status') == 'completed':
            return _fail('删除后草稿箱仍展示本次标题', {'title': title, 'row': found.get('element')})
        await self.page.evaluate(r'''() => {
            const root=document.documentElement;
            root.setAttribute('data-ai-article-storage','deleted');
            root.removeAttribute('data-ai-article-pending-draft');
        }''')
        return _ok('已验证草稿箱不再展示本次标题', {'title': title, 'lookup': found.get('element')})

    async def open_article_editor(self, step) -> ActionResult:
        try:
            stage = await self.page.evaluate(r'''() => {
                const visible = el => { const r=el.getBoundingClientRect(), s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
                const text=String(document.body?.innerText || '');
                const pickerRoots=Array.from(document.querySelectorAll('[role="dialog"],[aria-modal="true"],[class*="modal" i],[class*="dialog" i]')).filter(visible);
                const typePicker=pickerRoots.some(root=>/选择发布类型/.test(String(root.innerText||root.textContent||'')));
                const widgets=Array.from(document.querySelectorAll('[class*="w-e-"],[class*="editor" i],[class*="publish" i]')).filter(visible);
                const editorPage=/(?:发布设置|存草稿|公告发布|活动发布|攻略发布)/.test(text);
                return {typePicker, editor:editorPage&&widgets.length>0, editorPage, editorWidgetCount:widgets.length};
            }''')
            if stage.get('typePicker') or stage.get('editor'):
                return _ok('文章发布编辑器已打开', {'stage': stage})

            # Imported cases sometimes describe a non-existent "content
            # management -> publish" route. If that modal is open, close it
            # first so the real toolbar publish control is actionable.
            dismiss = await self.page.evaluate(r'''() => {
                const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
                const dialogs=Array.from(document.querySelectorAll('[role="dialog"],[aria-modal="true"],[class*="modal" i],[class*="dialog" i]')).filter(visible);
                const root=dialogs.find(el => /发布中|草稿箱|已下架/.test(String(el.innerText||el.textContent||'')));
                if(!root)return {found:false};
                const close=Array.from(root.querySelectorAll('button,[role="button"],[aria-label]')).filter(visible).find(el => /^(?:关闭|close|×|✕|✖)$/.test(String(el.innerText||el.textContent||el.getAttribute('aria-label')||'').replace(/\s+/g,'')) || /close/i.test(String(el.className||'')+' '+String(el.getAttribute('aria-label')||'')));
                if(!close)return {found:false, modal:true};
                const token='ai_article_management_close_'+Date.now(); close.setAttribute('data-ai-article-management-close',token); return {found:true,selector:'[data-ai-article-management-close="'+token+'"]'};
            }''')
            if dismiss and dismiss.get('found'):
                await self.page.locator(dismiss['selector']).click(timeout=3000)
                await asyncio.sleep(0.25)
        except Exception as exc:
            return _fail(f'准备文章编辑器失败: {str(exc)[:200]}')
        return await self._click_article_candidate(
            '发布编辑器',
            r'^发布$',
            r'''() => { const visible=el => {const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';}; const bodyText=String(document.body?.innerText || ''); const dialogs=Array.from(document.querySelectorAll('[role="dialog"],[aria-modal="true"],[class*="modal" i],[class*="dialog" i]')).filter(visible); const typePicker=dialogs.some(root=>/选择发布类型/.test(String(root.innerText||root.textContent||''))); const widgets=Array.from(document.querySelectorAll('[class*="w-e-"],[class*="editor" i],[class*="publish" i]')).filter(visible); const editorPage=/(?:发布设置|存草稿|公告发布|活动发布|攻略发布)/.test(bodyText); return {passed:typePicker||(editorPage&&widgets.length>0), stage:typePicker?'type_picker':(editorPage?'editor':'none'), editorPage, editorWidgetCount:widgets.length}; }''',
        )

    async def select_article_type(self, step) -> ActionResult:
        article_type = str(step.get('article_type') or step.get('target_text') or '').strip()
        if article_type not in {'活动', '公告', '攻略'}:
            return _fail(f'不支持的文章发布类型: {article_type or "空"}')
        try:
            scan = await self.page.evaluate(r'''(articleType) => {
                const visible = el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0'; };
                const norm = value => String(value || '').replace(/\s+/g, '').trim();
                const roots = Array.from(document.querySelectorAll('[role="dialog"],[aria-modal="true"],[class*="modal" i],[class*="dialog" i]')).filter(visible);
                const picker = roots.find(root => /选择发布类型/.test(String(root.innerText || root.textContent || '')));
                if (!picker) {
                    return {found:false, reason:'当前编辑器未展示“选择发布类型”，禁止从文章列表或分类标签中猜测类型选项'};
                }
                const candidates = Array.from(picker.querySelectorAll('button,[role="button"],a,div,span')).filter(visible).map(source => {
                    const text = norm(source.innerText || source.textContent || '');
                    if (text !== articleType) return null;
                    const clickable = source.closest('button,[role="button"],a,[class*="cursor-pointer" i]') || source;
                    if (!picker.contains(clickable)) return null;
                    const r = clickable.getBoundingClientRect();
                    return {el:clickable, rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
                }).filter(Boolean);
                const best = candidates[0];
                if (!best) return {found:false, reason:'发布类型选择器中未找到目标类型 '+articleType};
                const token='ai_article_type_picker_'+Date.now()+'_'+Math.random().toString(36).slice(2);
                best.el.setAttribute('data-ai-article-type-picker', token);
                return {found:true, selector:'[data-ai-article-type-picker="'+token+'"]', rect:best.rect};
            }''', article_type)
            _log(self.execution_record, f'BUSINESS_ACTION nn_select_article_type scoped_scan={scan}')
            if not scan.get('found'):
                return _fail('未找到可用的文章发布类型选择器', {'scan': scan, 'article_type': article_type})
            await self.page.locator(scan['selector']).click(timeout=5000)
            await asyncio.sleep(0.4)
            state = await self.page.evaluate(r'''() => {
                const visible = el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
                const text=String(document.body?.innerText || '');
                const fields=Array.from(document.querySelectorAll('input,textarea,[contenteditable="true"]')).filter(visible);
                return {editorOpen:fields.length>0, pickerOpen:/选择发布类型/.test(text)};
            }''')
            if not state.get('editorOpen') or state.get('pickerOpen'):
                return _fail('选择发布类型后未进入对应编辑器', {'scan': scan, 'state': state})
            return _ok(f'已选择文章发布类型「{article_type}」', {'scan': scan, 'state': state})
        except Exception as exc:
            return _fail(f'选择文章发布类型失败: {str(exc)[:200]}')

    async def verify_article_type_immutable(self, step) -> ActionResult:
        article_type = str(step.get('article_type') or step.get('target_text') or '').strip()
        if article_type not in {'活动', '公告', '攻略'}:
            return _fail('验证文章类型不可变缺少有效类型')
        context = await self._article_runtime_context()
        title = context.get('title', '').strip()
        try:
            state = await self.page.evaluate(r'''(payload) => {
                const visible = el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
                const text=String(document.body?.innerText || '');
                const inputs=Array.from(document.querySelectorAll('input')).filter(visible);
                const titleInput=inputs.some(el => String(el.value || '').includes(payload.title));
                const editor=Array.from(document.querySelectorAll('[contenteditable="true"],textarea')).some(visible);
                const picker=/选择发布类型/.test(text);
                const marker=text.includes(payload.articleType + '发布');
                return {titleInput, editor, picker, marker, text:text.slice(0,1200)};
            }''', {'title': title, 'articleType': article_type})
            if not state.get('titleInput') or not state.get('editor'):
                return _fail('未处于本次文章的编辑器，无法验证发布类型状态', {'title': title, 'state': state})
            if state.get('picker'):
                return _fail('编辑态仍展示发布类型选择器，类型可修改，与当前用例预期不符', {'state': state})
            if not state.get('marker'):
                return _fail('编辑态未展示当前文章类型标识', {'article_type': article_type, 'state': state})
            return _ok(f'已验证已发布{article_type}文章编辑态类型不可修改', {'title': title, 'state': state})
        except Exception as exc:
            return _fail(f'验证文章发布类型不可变失败: {str(exc)[:200]}')

    async def close_article_editor(self, step) -> ActionResult:
        try:
            scan = await self.page.evaluate(r'''() => {
                const visible = el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
                const roots=Array.from(document.querySelectorAll('[role="dialog"],[aria-modal="true"],[class*="modal" i],[class*="dialog" i]')).filter(visible);
                const fields=Array.from(document.querySelectorAll('input,textarea,[contenteditable="true"]')).filter(visible);
                const editorField=fields.find(el => el.isContentEditable || el.tagName==='TEXTAREA') || Array.from(document.querySelectorAll('[class*="w-e-"],[class*="editor" i],[class*="publish" i]')).filter(visible)[0];
                const root=roots.find(el => el.contains(editorField)) || editorField?.closest('[class*="publish" i],[class*="editor" i]') || document.body;
                if(!editorField || !/(?:发布设置|存草稿|公告发布|活动发布|攻略发布)/.test(String(document.body?.innerText||''))) return {found:false, reason:'未找到处于打开状态的文章编辑器'};
                const rr=root.getBoundingClientRect();
                const candidates=Array.from(root.querySelectorAll('button,[role="button"],[aria-label],svg,span,div,i')).filter(visible).map(el => {
                    const text=String(el.innerText||el.textContent||el.getAttribute('aria-label')||'').replace(/\s+/g,'');
                    const cls=String(el.className||'')+' '+String(el.getAttribute('aria-label')||'');
                    const r=el.getBoundingClientRect();
                    const closeMark=/^(关闭|close|×|✕|✖)$/.test(text)||/close|dismiss/i.test(cls);
                    const topRight=r.left>=rr.right-100&&r.top<=rr.top+100&&r.width<=90&&r.height<=90;
                    const score=(closeMark?5000:0)+(topRight?1800:0)+(el.tagName==='BUTTON'||el.getAttribute('role')==='button'?600:0);
                    return {el,r,score};
                }).filter(item=>item.score>=2400 || (item.score>=1800 && item.r.width<=48 && item.r.height<=48)).sort((a,b)=>b.score-a.score);
                const best=candidates[0];
                if(!best)return {found:false, reason:'未找到文章编辑器关闭控件'};
                const token='ai_article_editor_close_'+Date.now(); best.el.setAttribute('data-ai-article-editor-close',token);
                return {found:true,selector:'[data-ai-article-editor-close="'+token+'"]'};
            }''')
            if not scan.get('found'):
                return _fail('关闭文章编辑器失败', {'scan': scan})
            await self.page.locator(scan['selector']).click(timeout=5000)
            deadline=time.monotonic()+4
            while time.monotonic()<deadline:
                state=await self._article_editor_state()
                if not state.get('open'):
                    return _ok('已关闭文章编辑器', {'scan': scan, 'state': state})
                await asyncio.sleep(0.2)
            return _fail('点击关闭后文章编辑器仍处于打开状态', {'scan': scan, 'state': state})
        except Exception as exc:
            return _fail(f'关闭文章编辑器失败: {str(exc)[:200]}')

    async def submit_article(self, step, save_as_draft=False) -> ActionResult:
        label = '存草稿' if save_as_draft else '发布'
        try:
            result = await self._click_article_candidate(label, '^' + re.escape(label) + '$')
            if result.get('status') != 'completed':
                return result
            if save_as_draft:
                # Saving a draft does not close this site's editor and it may
                # not render a persistent toast.  Record the pending commit;
                # open_article_management performs the authoritative check in
                # 草稿箱 before this run can be considered successful.
                submit_state = await self.page.evaluate(r'''() => {
                    const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
                    const feedback=[...new Set(Array.from(document.querySelectorAll('body *')).filter(visible).map(el=>String(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim()).filter(text=>text&&text.length<=160&&/不允许发布|发布过于频繁|操作过于频繁|敏感内容|保存成功|已保存|操作成功/.test(text)))];
                    const text=String(document.body?.innerText||'');
                    return {blocked:/不允许发布|发布过于频繁|操作过于频繁/.test(text), sensitive:/标题.*敏感内容|敏感内容.*标题/.test(text), feedback};
                }''')
                if submit_state.get('blocked'):
                    return _fail('保存草稿被站点频控限制，未产生可校验草稿', {
                        **(result.get('element') or {}),
                        'commit_state': submit_state,
                    })
                if submit_state.get('sensitive'):
                    return _fail('保存草稿被页面内容规则拒绝，未产生可校验草稿', {
                        **(result.get('element') or {}),
                        'commit_state': submit_state,
                    })
                context = await self._article_runtime_context()
                if not context.get('title'):
                    return _fail('保存草稿前缺少本次运行标题，无法进行后续数据校验')
                await self.page.evaluate(r'''() => {
                    const root=document.documentElement;
                    root.setAttribute('data-ai-article-storage','draft');
                    root.setAttribute('data-ai-article-pending-draft','true');
                }''')
                return _ok(
                    '已提交存草稿，待内容管理草稿箱校验',
                    {**(result.get('element') or {}), 'title': context['title'], 'verification_required': 'draft_management'},
                )
            async def publish_state():
                return await self.page.evaluate(r'''() => {
                    const visible = el => {
                        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
                        return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
                    };
                    const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
                    const text = String(document.body?.innerText || '');
                    const dialogs = Array.from(document.querySelectorAll('[role="dialog"],[aria-modal="true"],[class*="modal" i],[class*="dialog" i]')).filter(visible);
                    const confirmOpen = dialogs.some(el => /确认发布|确定发布|确认提交|确定提交/.test(norm(el.innerText || el.textContent || '')));
                    const feedback = Array.from(document.querySelectorAll('body *')).filter(visible).map(el => norm(el.innerText || el.textContent || '')).filter(value => value && value.length <= 120 && /敏感内容|请输入|不允许发布|发布成功|保存成功|操作成功/.test(value));
                    const validationMessages = [...new Set(feedback.filter(value => /敏感内容|请输入|不允许发布/.test(value)))];
                    const editorFields = Array.from(document.querySelectorAll('input,textarea,[contenteditable="true"]')).filter(visible);
                    return {
                        confirmOpen,
                        success: /发布成功|保存成功|已保存|操作成功/.test(text),
                        editorOpen: editorFields.length > 0,
                        publishBlocked: /不允许发布|发布过于频繁|操作过于频繁/.test(text),
                        titleSensitive: /标题.*敏感内容|敏感内容.*标题/.test(text),
                        validationMessages,
                        text: text.slice(-900),
                    };
                }''')

            state = await publish_state()
            if state.get('publishBlocked'):
                message = '; '.join(state.get('validationMessages') or []) or '当前账号暂时不允许发布'
                return _fail(f'文章发布被站点频控限制: {message}', {
                    **(result.get('element') or {}),
                    'commit_state': state,
                })
            if state.get('titleSensitive'):
                message = '; '.join(state.get('validationMessages') or []) or '标题包含敏感内容，请重新输入'
                return _fail(f'文章发布被页面拒绝: {message}', {
                    **(result.get('element') or {}),
                    'commit_state': state,
                })

            confirm = None if save_as_draft else await self.page.evaluate(r'''() => {
                const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
                const nodes=Array.from(document.querySelectorAll('button,[role="button"]')).filter(visible);
                const target=nodes.find(el => /^(确认发布|确定发布|确认)$/.test(String(el.innerText||el.textContent||'').replace(/\s+/g,'')));
                if(!target)return {found:false}; const token='ai_article_confirm_'+Date.now(); target.setAttribute('data-ai-article-confirm',token); return {found:true,selector:'[data-ai-article-confirm="'+token+'"]'};
            }''')
            if confirm and confirm.get('found'):
                await self.page.locator(confirm['selector']).click(timeout=8000)
                _log(self.execution_record, 'BUSINESS_ACTION nn_submit_article confirmed_publish_dialog=true')

            title = await self.page.evaluate('() => document.documentElement.getAttribute("data-ai-article-title") || ""')
            deadline = time.monotonic() + 8
            last_state = {}
            while time.monotonic() < deadline:
                last_state = await publish_state()
                if last_state.get('success') or (not last_state.get('editorOpen') and not last_state.get('confirmOpen')):
                    return _ok(
                        '文章已保存为草稿' if save_as_draft else '文章已发布',
                        {**(result.get('element') or {}), 'confirmed_publish_dialog': bool(confirm and confirm.get('found')), 'commit_state': last_state},
                    )
                await asyncio.sleep(0.35)
            return _fail(
                f'文章{label}后未检测到成功反馈或编辑器关闭',
                {**(result.get('element') or {}), 'confirmed_publish_dialog': bool(confirm and confirm.get('found')), 'commit_state': last_state},
            )
        except Exception as exc:
            return _fail(f'文章{label}失败: {str(exc)[:200]}')

    async def fill_article_field(self, step, field) -> ActionResult:
        source_value = str(step.get('input_value') or '').strip()
        if not source_value:
            return _fail('文章字段缺少输入值')
        generated_title = field == 'title' and _is_generated_article_title(step, source_value)
        generated_body = False
        if field == 'body':
            generated_body = await self.page.evaluate(
                '() => document.documentElement.getAttribute("data-ai-article-generated-title") === "true"'
            )
        value = (
            _safe_generated_article_title()
            if generated_title
            else (_safe_generated_article_body() if generated_body else source_value)
        )
        try:
            scan = await self.page.evaluate(r'''(field) => {
                const visible = el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
                const norm = value => String(value || '').replace(/\s+/g,' ').trim();
                const elements = Array.from(document.querySelectorAll('input,textarea,[contenteditable="true"],.ql-editor,.w-e-text,[role="textbox"]')).filter(visible);
                const candidates = elements.map(el => { const info=norm([el.getAttribute('placeholder'),el.getAttribute('aria-label'),el.getAttribute('name'),el.id,el.className,el.parentElement?.innerText].join(' ')); let score=0; if(field==='title'){ if(el.tagName==='INPUT')score+=1000; if(/标题|title/.test(info))score+=2600; if(/游戏.?id|game.?id/.test(info))score-=5000; } else { if(el.isContentEditable)score+=2800; if(el.tagName==='TEXTAREA')score+=1800; if(/editor|正文|内容|content|text/.test(info))score+=1500; if(/游戏.?id|title|标题/.test(info))score-=3500; } return {el,info,score}; }).filter(item=>item.score>0).sort((a,b)=>b.score-a.score);
                const best=candidates[0]; if(!best)return {found:false,samples:candidates.slice(0,5).map(item=>({info:item.info,score:item.score}))};
                const token='ai_article_field_'+Date.now()+'_'+Math.random().toString(36).slice(2); best.el.setAttribute('data-ai-article-field',token); return {found:true,selector:'[data-ai-article-field="'+token+'"]',detail:{score:best.score,info:best.info.slice(0,180),tag:best.el.tagName}};
            }''', field)
            _log(self.execution_record, f'BUSINESS_ACTION nn_fill_article_{field} scan={scan}')
            if not scan or not scan.get('found'):
                return _fail(f'未找到文章{ "标题" if field == "title" else "正文" }输入区域', {'scan': scan})
            locator = self.page.locator(scan['selector'])
            await _fill_and_verify(locator, value)
            actual = await locator.evaluate(r'''el => String(el.isContentEditable ? (el.innerText || el.textContent || '') : (el.value || ''))''')
            if value not in actual:
                return _fail(
                    f'文章{ "标题" if field == "title" else "正文" }写入后读取值不一致',
                    {'scan': scan, 'expected': value, 'actual': actual[:300]},
                )
            if field == 'title':
                if generated_title:
                    _log(self.execution_record, f'BUSINESS_ACTION nn_fill_article_title generated_value={value}')
                await self.page.evaluate(
                    r'''(payload) => {
                        const root=document.documentElement;
                        const current=root.getAttribute('data-ai-article-title') || '';
                        if(current && current !== payload.value) root.setAttribute('data-ai-article-previous-title', current);
                        root.setAttribute('data-ai-article-title', payload.value);
                        if(payload.generated) root.setAttribute('data-ai-article-generated-title', 'true');
                    }''',
                    {'value': value, 'generated': generated_title},
                )
            else:
                await self.page.evaluate(
                    '(value) => document.documentElement.setAttribute("data-ai-article-body", value)',
                    value,
                )
            evidence = {'scan': scan, 'value': value}
            if generated_title:
                evidence['source_value'] = source_value
                evidence['generated_runtime_value'] = True
            if generated_body:
                evidence['source_value'] = source_value
                evidence['generated_runtime_value'] = True
            return _ok(f'已输入文章{ "标题" if field == "title" else "正文" }', evidence)
        except Exception as exc:
            return _fail(f'输入文章字段失败: {str(exc)[:200]}')

    async def append_article_body(self, step) -> ActionResult:
        value = str(step.get('input_value') or '').strip()
        if not value:
            return _fail('追加正文缺少输入值')
        try:
            scan = await self.page.evaluate(r'''() => {
                const visible = el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
                const norm = value => String(value || '').replace(/\s+/g,' ').trim();
                const elements = Array.from(document.querySelectorAll('textarea,[contenteditable="true"],.ql-editor,.w-e-text,[role="textbox"]')).filter(visible);
                const candidates = elements.map(el => { const info=norm([el.getAttribute('placeholder'),el.getAttribute('aria-label'),el.getAttribute('name'),el.id,el.className,el.parentElement?.innerText].join(' ')); let score=0; if(el.isContentEditable)score+=2800; if(el.tagName==='TEXTAREA')score+=1800; if(/editor|正文|内容|content|text/.test(info))score+=1500; if(/游戏.?id|title|标题/.test(info))score-=3500; return {el,info,score}; }).filter(item=>item.score>0).sort((a,b)=>b.score-a.score);
                const best=candidates[0]; if(!best)return {found:false};
                const token='ai_article_append_body_'+Date.now()+'_'+Math.random().toString(36).slice(2); best.el.setAttribute('data-ai-article-append-body',token); return {found:true,selector:'[data-ai-article-append-body="'+token+'"]',detail:{score:best.score,info:best.info.slice(0,180)}};
            }''')
            if not scan.get('found'):
                return _fail('未找到文章正文编辑区域', {'scan': scan})
            locator = self.page.locator(scan['selector'])
            const_before = await locator.evaluate(r'''el => String(el.isContentEditable ? (el.innerText || el.textContent || '') : (el.value || ''))''')
            await locator.click(timeout=5000)
            await locator.press('Control+End', timeout=3000)
            await locator.type(value, timeout=10000)
            actual = await locator.evaluate(r'''el => String(el.isContentEditable ? (el.innerText || el.textContent || '') : (el.value || ''))''')
            if value not in actual or (const_before and const_before not in actual):
                return _fail('文章正文追加后读取值不一致', {'scan': scan, 'expected_append': value, 'before': const_before[:200], 'actual': actual[:400]})
            await self.page.evaluate(
                r'''(payload) => {
                    const root=document.documentElement;
                    root.setAttribute('data-ai-article-body', payload.actual);
                }''',
                {'actual': actual},
            )
            return _ok('已在文章正文末尾追加内容', {'scan': scan, 'value': value})
        except Exception as exc:
            return _fail(f'追加文章正文失败: {str(exc)[:200]}')

    async def open_login(self, step) -> ActionResult:
        reused = await self._already_logged_in()
        if reused:
            return reused
        result = await self.page.evaluate(r"""() => {
            const visible = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
            };
            const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
            const candidates = [];
            const seen = new Set();
            const pushCandidate = (clickEl, sourceText, source) => {
                if (!clickEl || !visible(clickEl) || seen.has(clickEl)) return;
                seen.add(clickEl);
                const text = norm(sourceText || clickEl.innerText || clickEl.textContent || clickEl.getAttribute('aria-label') || clickEl.getAttribute('alt') || '');
                const cls = String(clickEl.className || '');
                const alt = String(clickEl.getAttribute('alt') || '');
                const r = clickEl.getBoundingClientRect();
                let score = 0;
                if (/登录|登陆/.test(text)) score += 2600;
                if (/默认头像|头像|avatar/i.test(text + ' ' + alt + ' ' + cls)) score += 1200;
                if (r.left < 120) score += 900;
                if (r.top > window.innerHeight - 140) score += 1200;
                if (r.top < 160) score -= 300;
                if (/cursor-pointer/.test(cls)) score += 300;
                candidates.push({el: clickEl, score, text, cls: cls.slice(0, 160), rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}, source});
            };
            document.querySelectorAll('img[alt*="默认头像"], img[alt*="头像"], img[alt*="avatar" i]').forEach((el) => {
                pushCandidate(el.closest('button,a,[role="button"],[class*="cursor-pointer" i]') || el, el.getAttribute('alt') || '', 'avatar_img');
            });
            document.querySelectorAll('button,a,[role="button"],[class*="cursor-pointer" i],[class*="avatar" i],[class*="user" i]').forEach((el) => {
                if (!visible(el)) return;
                const text = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('alt') || '');
                const cls = String(el.className || '');
                const alt = String(el.getAttribute('alt') || '');
                if (!/(登录|登陆|默认头像|头像|avatar|user|profile)/i.test(text + ' ' + cls + ' ' + alt)) return;
                pushCandidate(el, text || alt, 'generic_clickable');
            });
            candidates.sort((a,b) => b.score - a.score);
            return {found: candidates.length > 0, candidates: candidates.slice(0,8).map((c,idx)=>{ const token='ai_nn_login_entry_' + idx + '_' + Date.now() + '_' + Math.random().toString(36).slice(2); c.el.setAttribute('data-ai-automation-click-target', token); return {selector:'[data-ai-automation-click-target="'+token+'"]', score:c.score, text:c.text, cls:c.cls, rect:c.rect, source:c.source}; })};
        }""")
        _log(self.execution_record, f'BUSINESS_ACTION nn_open_login scan={result}')
        if not result or not result.get('found'):
            return _fail('未找到 NN 登录入口')

        for cand in result.get('candidates', [])[:6]:
            loc = self.page.locator(cand['selector']).first
            click_methods = []
            try:
                box = await loc.bounding_box()
            except Exception:
                box = None
            click_methods.append('locator_click')
            if box:
                click_methods.extend(['mouse_center_click', 'mouse_move_down_up'])
            click_methods.append('dom_click')

            for method in click_methods:
                try:
                    if method == 'locator_click':
                        await loc.click(timeout=3000)
                    elif method == 'mouse_center_click' and box:
                        x = box['x'] + box['width'] / 2
                        y = box['y'] + box['height'] / 2
                        await self.page.mouse.click(x, y)
                    elif method == 'mouse_move_down_up' and box:
                        x = box['x'] + box['width'] / 2
                        y = box['y'] + box['height'] / 2
                        await self.page.mouse.move(x, y)
                        await asyncio.sleep(0.15)
                        await self.page.mouse.down()
                        await asyncio.sleep(0.05)
                        await self.page.mouse.up()
                    else:
                        await self.page.evaluate('(s) => { const e = document.querySelector(s); if (e) e.click(); }', cand['selector'])
                except Exception as exc:
                    _log(self.execution_record, f'BUSINESS_ACTION nn_open_login click_method_failed method={method} selector={cand["selector"]} error={str(exc)[:160]}')
                    continue
                await asyncio.sleep(1.5)
                phone_selector, phone, dialog = await _find_login_field(self.page, self.PHONE_SELECTORS, timeout=1200)
                code_selector, code, dialog = await _find_login_field(self.page, self.CODE_SELECTORS, timeout=800)
                if phone or code:
                    _log(self.execution_record, f'BUSINESS_ACTION nn_open_login dialog_hit={dialog}')
                    return _ok('NN 登录弹窗已打开', {'selector': cand['selector'], 'detail': {**cand, 'click_method': method, 'dialog': dialog, 'phone_selector': phone_selector, 'code_selector': code_selector}})

        diag = await self.page.evaluate(r"""() => {
            const visible = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
            };
            const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
            const dialogs = Array.from(document.querySelectorAll('[role="dialog"], .nn-dialog, .nn-modal, .modal, .dialog, [class*="dialog" i], [class*="modal" i]')).filter(visible).map((el) => { const r = el.getBoundingClientRect(); return {text: norm(el.innerText || '').slice(0, 240), cls: String(el.className || '').slice(0, 160), rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}}; });
            const inputs = Array.from(document.querySelectorAll('input, textarea')).filter(visible).map((el) => { const r = el.getBoundingClientRect(); return {type: el.getAttribute('type') || '', placeholder: el.getAttribute('placeholder') || '', name: el.getAttribute('name') || '', value: (el.value || '').slice(0, 80), cls: String(el.className || '').slice(0, 120), rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}}; });
            return {url: location.href, title: document.title, dialogs, inputs: inputs.slice(0, 12)};
        }""")
        _log(self.execution_record, f'BUSINESS_ACTION nn_open_login post_click_diag={diag}')
        return _fail('点击多个登录入口候选后仍未出现手机号/验证码登录弹窗', {'scan': result, 'diag': diag})

    async def fill_phone(self, step) -> ActionResult:
        reused = await self._already_logged_in()
        if reused:
            return reused
        value = str(step.get('input_value') or '')
        selector, loc, dialog = await _find_login_field(self.page, self.PHONE_SELECTORS)
        if not loc:
            opened = await self.open_login({'description': '自动打开登录入口'})
            if opened.get('status') == 'completed':
                selector, loc, dialog = await _find_login_field(self.page, self.PHONE_SELECTORS)
            if not loc:
                return _fail('未找到手机号/账号输入框，自动唤起登录流程后仍未出现', {'dialog': dialog, 'open_login': opened})
        if not await _fill_and_verify(loc, value):
            return _fail('手机号/账号输入后读取值不一致', {'selector': selector, 'dialog': dialog})
        _log(self.execution_record, f'BUSINESS_ACTION nn_fill_phone selector={selector} dialog={dialog}')
        return _ok('已输入手机号/账号', {'selector': selector, 'dialog': dialog, 'value': value})

    async def fill_verification_code(self, step) -> ActionResult:
        reused = await self._already_logged_in()
        if reused:
            return reused
        value = str(step.get('input_value') or '')
        selector, loc, dialog = await _find_login_field(self.page, self.CODE_SELECTORS)
        if not loc:
            opened = await self.open_login({'description': '自动打开登录入口'})
            if opened.get('status') == 'completed':
                selector, loc, dialog = await _find_login_field(self.page, self.CODE_SELECTORS)
            if not loc:
                return _fail('未找到验证码输入框，自动唤起登录流程后仍未出现', {'dialog': dialog, 'open_login': opened})
        if not await _fill_and_verify(loc, value):
            return _fail('验证码输入后读取值不一致', {'selector': selector, 'dialog': dialog})
        _log(self.execution_record, f'BUSINESS_ACTION nn_fill_verification_code selector={selector} dialog={dialog}')
        return _ok('已输入验证码', {'selector': selector, 'dialog': dialog, 'value': value})

    async def fill_password(self, step) -> ActionResult:
        reused = await self._already_logged_in()
        if reused:
            return reused
        value = str(step.get('input_value') or '')
        selector, loc, dialog = await _find_login_field(self.page, self.PASSWORD_SELECTORS)
        if not loc:
            opened = await self.open_login({'description': '自动打开登录入口'})
            if opened.get('status') == 'completed':
                selector, loc, dialog = await _find_login_field(self.page, self.PASSWORD_SELECTORS)
            if not loc:
                return _fail('未找到密码输入框，自动唤起登录流程后仍未出现', {'dialog': dialog, 'open_login': opened})
        if not await _fill_and_verify(loc, value):
            return _fail('密码输入后读取值不一致', {'selector': selector, 'dialog': dialog})
        _log(self.execution_record, f'BUSINESS_ACTION nn_fill_password selector={selector} dialog={dialog}')
        return _ok('已输入密码', {'selector': selector, 'dialog': dialog, 'value': value})

    async def submit_login(self, step, require_success: bool = False) -> ActionResult:
        reused = await self._already_logged_in()
        if reused:
            return reused
        dialog = await _find_best_login_dialog(self.page)
        form_state = await _visible_login_form_state(self.page)
        _log(self.execution_record, f'BUSINESS_ACTION nn_submit_login dialog={dialog} form_state={form_state}')
        if not form_state.get('passed'):
            return _fail(form_state.get('reason') or '当前页面未检测到真实登录表单/弹窗，禁止继续执行登录提交', {'dialog': dialog, 'login_form_state': form_state})

        result = await self.page.evaluate(r"""(dialogSelector) => {
            const visible = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
            };
            const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
            const root = dialogSelector ? document.querySelector(dialogSelector) : null;
            const roots = [];
            if (root && visible(root)) roots.push(root);
            Array.from(document.querySelectorAll('[role="dialog"], .nn-dialog, .nn-modal, .modal, .dialog, [class*="dialog" i], [class*="modal" i]')).filter(visible).forEach((el) => {
                if (!roots.includes(el)) roots.push(el);
            });
            if (roots.length === 0) roots.push(document.body);
            const candidates = [];
            for (const root of roots) {
                for (const el of Array.from(root.querySelectorAll('button,[role="button"],.nn-button,.el-button,a'))) {
                    if (!visible(el)) continue;
                    const text = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
                    const cls = String(el.className || '');
                    if (!/登录|登陆|注册|login|sign/i.test(text + ' ' + cls)) continue;
                    const r = el.getBoundingClientRect();
                    let score = 0;
                    if (/登录\s*\/\s*注册|登录|登陆|注册/.test(text)) score += 1000;
                    if (/primary|button--primary/i.test(cls)) score += 200;
                    if (dialogSelector && root === document.querySelector(dialogSelector)) score += 1200;
                    score -= Math.max(0, text.length - 12) * 10;
                    candidates.push({el, text, cls: cls.slice(0, 120), rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}, score});
                }
            }
            candidates.sort((a, b) => b.score - a.score);
            const best = candidates[0];
            if (!best) return {found: false, candidates: []};
            const token = 'ai_nn_login_submit_' + Date.now() + '_' + Math.random().toString(36).slice(2);
            best.el.setAttribute('data-ai-automation-click-target', token);
            return {found: true, selector: '[data-ai-automation-click-target="' + token + '"]', detail: {text: best.text, cls: best.cls, rect: best.rect, score: best.score}};
        }""", dialog['selector'] if dialog else None)
        _log(self.execution_record, f'BUSINESS_ACTION nn_submit_login submit_scan={result}')
        if not result or not result.get('found'):
            return _fail('未找到登录/注册提交按钮', {'dialog': dialog, 'login_form_state': form_state})
        loc = self.page.locator(result['selector']).first
        submitted_values = await self.page.evaluate(r'''(dialogSelector) => {
            const visible=el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
            const root=document.querySelector(dialogSelector) || document.body;
            const fields=Array.from(root.querySelectorAll('input')).filter(visible);
            const pick=pattern => fields.find(el => pattern.test(String(el.placeholder||'')+' '+String(el.name||'')));
            const phone=pick(/手机|phone|mobile/i);
            const code=pick(/验证码|校验码|code|captcha/i);
            return {phone:String(phone?.value||''), code:String(code?.value||'')};
        }''', dialog['selector'] if dialog else '')
        await loc.click(timeout=5000, force=True)
        busy_state = {'observed': False, 'detached': False}
        for _ in range(20):
            busy_state = await self.page.evaluate(r"""(selector) => {
                const el = document.querySelector(selector);
                if (!el) return {observed: false, detached: true, reason: '提交后按钮已离开当前表单'};
                const text = String(el.innerText || el.textContent || el.value || '').replace(/\s+/g, ' ').trim();
                const meta = `${text} ${el.className || ''} ${el.getAttribute('aria-busy') || ''}`;
                const disabled = !!el.disabled || el.getAttribute('aria-disabled') === 'true';
                const busy = disabled || el.getAttribute('aria-busy') === 'true' || /loading|处理中|提交中|登录中|加载中|is-loading/i.test(meta) || !!el.querySelector('[class*="loading" i],[class*="spinner" i],.el-loading-spinner');
                return {observed: busy, detached: false, disabled, ariaBusy: el.getAttribute('aria-busy'), text, cls: String(el.className || '').slice(0, 160)};
            }""", result['selector'])
            if busy_state.get('observed'):
                break
            await asyncio.sleep(0.05)
        if require_success:
            # NN's SMS-login response can close the dialog several seconds
            # after the submit button stops showing its busy state.  Poll the
            # outcome of this one submission instead of clicking it again.
            state = None
            remaining_form = None
            for _ in range(20):
                state = await evaluate_login_success(self.page)
                if state.get('passed'):
                    return _ok('登录成功', {
                        'selector': result['selector'],
                        'login_state': state,
                        'dialog': dialog,
                        'busy_state': busy_state,
                    })
                remaining_form = await _visible_login_form_state(self.page)
                await asyncio.sleep(0.4)
            state = state or await evaluate_login_success(self.page)
            if not state.get('passed'):
                remaining_form = remaining_form or await _visible_login_form_state(self.page)
                if remaining_form.get('passed'):
                    return _fail(state.get('reason') or '提交登录后登录表单仍可见', {'selector': result['selector'], 'login_state': state, 'dialog': dialog, 'login_form_state': remaining_form, 'busy_state': busy_state})
                # Closing a dialog is not login evidence.  The NN test site
                # can occasionally return an unauthenticated shell on the
                # first submit, then accept the exact same test credentials
                # after a fresh same-origin page load.  Retry the complete
                # form once; never let a protected case continue as a guest.
                retry_count = int(step.get('_login_retry') or 0)
                if retry_count < 1:
                    values = submitted_values or {}
                    if values.get('phone') and values.get('code'):
                        origin = await self.page.evaluate('() => location.origin')
                        await self.page.goto(origin + '/', wait_until='domcontentloaded', timeout=30000)
                        await asyncio.sleep(0.6)
                        reopened = await self.open_login({'description': '认证未确认后重新打开登录弹窗'})
                        if reopened.get('status') == 'completed':
                            phone_result = await self.fill_phone({'input_value': values['phone']})
                            code_result = await self.fill_verification_code({'input_value': values['code']})
                            if phone_result.get('status') == 'completed' and code_result.get('status') == 'completed':
                                retried = await self.submit_login(
                                    {**step, '_login_retry': retry_count + 1},
                                    require_success=True,
                                )
                                if retried.get('status') == 'completed':
                                    retried.setdefault('element', {})['retry_after_unverified_login'] = True
                                    return retried
                                return retried
                return _fail(
                    state.get('reason') or '提交登录后未检测到真实认证状态',
                    {'selector': result['selector'], 'login_state': state, 'dialog': dialog, 'login_form_state': remaining_form, 'busy_state': busy_state},
                )
        return _ok('已提交登录', {'selector': result['selector'], 'detail': result.get('detail'), 'dialog': dialog, 'login_form_state': form_state, 'busy_state': busy_state})

    async def _hall_composer(self) -> ActionResult:
        try:
            scan = await self.page.evaluate(r'''() => {
                const visible = el => { const r=el.getBoundingClientRect(), s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&r.bottom>0&&r.top<innerHeight; };
                const candidates=Array.from(document.querySelectorAll('[contenteditable]')).filter(visible).map(el => {
                    const r=el.getBoundingClientRect(); const cls=String(el.className||'');
                    let score=0;
                    if(/chat-input/i.test(cls))score+=5000;
                    if(r.top>innerHeight*0.6)score+=1500;
                    if(r.width>300)score+=500;
                    return {el,r,cls,score};
                }).sort((a,b)=>b.score-a.score);
                const best=candidates[0];
                if(!best || best.score<1500)return {found:false, samples:candidates.slice(0,4).map(x=>({cls:x.cls,score:x.score}))};
                const token='ai-hall-composer-'+Date.now()+'-'+Math.random().toString(36).slice(2);
                best.el.setAttribute('data-ai-hall-composer',token);
                return {found:true, selector:'[data-ai-hall-composer="'+token+'"]', detail:{cls:best.cls.slice(0,180),rect:{x:Math.round(best.r.x),y:Math.round(best.r.y),w:Math.round(best.r.width),h:Math.round(best.r.height)}}};
            }''')
            return _ok('已定位成员大厅消息输入框', scan) if scan.get('found') else _fail('未找到成员大厅底部消息输入框', scan)
        except Exception as exc:
            return _fail(f'定位成员大厅消息输入框失败: {str(exc)[:200]}')

    async def _hall_context(self) -> Dict[str, str]:
        page_context = await self.page.evaluate(r'''() => {
            const root=document.documentElement;
            return {last:root.getAttribute('data-ai-hall-last-message')||'', original:root.getAttribute('data-ai-hall-original-message')||'', reply:root.getAttribute('data-ai-hall-reply-message')||'', emoji:root.getAttribute('data-ai-hall-emoji-src')||'', last_message_token:root.getAttribute('data-ai-hall-last-message-token')||'', original_message_token:root.getAttribute('data-ai-hall-original-message-token')||'', reply_message_token:root.getAttribute('data-ai-hall-reply-message-token')||'', emoji_message_token:root.getAttribute('data-ai-hall-emoji-message-token')||''};
        }''')
        record_id = getattr(self.execution_record, 'id', None)
        cached = HALL_RUNTIME_CONTEXTS.get(record_id, {}) if record_id else {}
        return {key: str(cached.get(key) or page_context.get(key) or '') for key in ('last', 'original', 'reply', 'emoji', 'last_message_token', 'original_message_token', 'reply_message_token', 'emoji_message_token')}

    async def _hall_set_context(self, **values) -> None:
        record_id = getattr(self.execution_record, 'id', None)
        if record_id:
            HALL_RUNTIME_CONTEXTS.setdefault(record_id, {}).update({key: str(value or '') for key, value in values.items()})
        await self.page.evaluate(r'''values => {
            const root=document.documentElement;
            for(const [key,value] of Object.entries(values||{})) {
                const name='data-ai-hall-'+key.replaceAll('_','-');
                if(value)root.setAttribute(name,String(value)); else root.removeAttribute(name);
            }
        }''', values)

    async def fill_hall_message(self, step) -> ActionResult:
        value=str(step.get('input_value') or '').strip()
        if not value:
            return _fail('成员大厅消息缺少输入内容')
        composer = await self._hall_composer()
        if composer.get('status') != 'completed':
            return composer
        try:
            locator=self.page.locator(composer['element']['selector'])
            await locator.fill(value, timeout=8000)
            actual=await locator.inner_text(timeout=1500)
            if value not in str(actual or ''):
                return _fail('成员大厅消息输入后未保留在输入框', {'expected':value,'actual':actual,'composer':composer.get('element')})
            await self._hall_set_context(last=value)
            return _ok('已在成员大厅输入唯一消息', {'value':value,'composer':composer.get('element')})
        except Exception as exc:
            return _fail(f'输入成员大厅消息失败: {str(exc)[:200]}', {'composer':composer.get('element')})

    async def _hall_message_visible(self, value: str, emoji_src: str = '', message_token: str = '') -> Dict[str, Any]:
        return await self.page.evaluate(r'''payload => {
            const visible=el => {const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&r.bottom>0&&r.top<innerHeight;};
            const composer=document.querySelector('[data-ai-hall-composer]');
            const text=String(payload.value||'').trim();
            const nodes=Array.from(document.querySelectorAll('div,span,p')).filter(visible).filter(el=>{const r=el.getBoundingClientRect(); return !composer?.contains(el)&&!el.closest('[contenteditable]')&&r.left>innerWidth*.45&&r.top>120&&r.bottom<innerHeight-5;});
            const exact=text ? nodes.filter(el=>String(el.innerText||el.textContent||'').trim()===text) : [];
            const insideEmojiPanel=el=>{for(let node=el.parentElement,depth=0;node&&depth<8;depth+=1,node=node.parentElement){if(/自定义表情/.test(String(node.innerText||node.textContent||'')))return true;}return false;};
            const marked=payload.message_token ? Array.from(document.querySelectorAll('[data-ai-hall-message-token]')).filter(visible).filter(el=>el.getAttribute('data-ai-hall-message-token')===payload.message_token) : [];
            const emoji=payload.emoji_src ? Array.from(document.querySelectorAll('img')).filter(visible).filter(el=>String(el.getAttribute('src')||'')===payload.emoji_src && !el.closest('[class*="emoji-panel" i],[class*="emotion-panel" i]') && !insideEmojiPanel(el)) : [];
            return {textCount:exact.length,emojiCount:emoji.length,markedCount:marked.length,found:payload.message_token ? marked.length>0 : (text ? exact.length>0 : emoji.length>0)};
        }''', {'value':value, 'emoji_src':emoji_src, 'message_token':message_token})

    async def send_hall_message(self, step) -> ActionResult:
        value=str(step.get('input_value') or '').strip()
        if value:
            filled=await self.fill_hall_message({**step,'input_value':value})
            if filled.get('status') != 'completed': return filled
        context=await self._hall_context()
        value=value or context.get('last','')
        if not value:
            return _fail('发送成员大厅消息前输入框没有本次唯一消息')
        composer=await self._hall_composer()
        if composer.get('status') != 'completed': return composer
        try:
            await self.page.locator(composer['element']['selector']).press('Enter', timeout=8000)
            for _ in range(12):
                await asyncio.sleep(0.4)
                draft=await self.page.locator(composer['element']['selector']).inner_text(timeout=1500)
                if value in str(draft or ''):
                    continue
                sent=await self._hall_message_visible(value)
                if sent.get('found'):
                    role=str(step.get('message_role') or 'last')
                    identity=await self.page.evaluate(r'''value => {
                        const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&r.bottom>0&&r.top<innerHeight;};
                        const own=el=>{const r=el.getBoundingClientRect();return r.left>innerWidth*.45&&r.top>120&&r.bottom<innerHeight-60;};
                        const target=Array.from(document.querySelectorAll('div,span,p')).filter(visible).filter(own).filter(el=>String(el.innerText||el.textContent||'').trim()===value).sort((a,b)=>a.getBoundingClientRect().width-b.getBoundingClientRect().width)[0];
                        if(!target)return {found:false};
                        const token='ai-hall-text-message-'+Date.now()+'-'+Math.random().toString(36).slice(2);
                        target.setAttribute('data-ai-hall-message-token',token);
                        const r=target.getBoundingClientRect();
                        return {found:true,token,rect:{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)}};
                    }''', value)
                    updates={'last':value}
                    if identity.get('found'):
                        updates['last_message_token']=identity['token']
                    if role=='original':
                        updates['original']=value
                        if identity.get('found'): updates['original_message_token']=identity['token']
                    if role=='reply':
                        updates['reply']=value
                        if identity.get('found'): updates['reply_message_token']=identity['token']
                    await self._hall_set_context(**updates)
                    return _ok('成员大厅唯一消息已发送并出现在消息流', {'value':value,'evidence':sent,'identity':identity,'composer':composer.get('element')})
            return _fail('发送后消息流未出现本次唯一消息', {'value':value,'evidence':await self._hall_message_visible(value)})
        except Exception as exc:
            return _fail(f'发送成员大厅消息失败: {str(exc)[:200]}', {'value':value})

    async def open_hall_emoji_panel(self, step) -> ActionResult:
        try:
            scan=await self.page.evaluate(r'''() => {
                const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&r.bottom>0&&r.top<innerHeight;};
                const panel=Array.from(document.querySelectorAll('div')).find(el=>visible(el)&&/自定义表情/.test(String(el.innerText||el.textContent||''))&&el.getBoundingClientRect().width>=280);
                if(panel||Array.from(document.querySelectorAll('img.window-emoji')).some(visible))return {found:true,already_open:true};
                const target=Array.from(document.querySelectorAll('button')).find(el=>visible(el)&&el.querySelector('i[class*="emotion" i]'));
                if(!target)return {found:false}; const token='ai-hall-emoji-button-'+Date.now(); target.setAttribute('data-ai-hall-emoji-button',token); return {found:true,selector:'[data-ai-hall-emoji-button="'+token+'"]'};
            }''')
            if not scan.get('found'): return _fail('未找到成员大厅输入区表情按钮', scan)
            if scan.get('already_open'): return _ok('成员大厅表情面板已打开', {'panel_visible':True})
            await self.page.locator(scan['selector']).click(timeout=5000)
            state=False
            for _ in range(12):
                await asyncio.sleep(0.25)
                state=await self.page.evaluate(r'''() => { const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&r.bottom>0&&r.top<innerHeight;}; return Array.from(document.querySelectorAll('img.window-emoji')).some(visible)||Array.from(document.querySelectorAll('div')).some(el=>visible(el)&&/自定义表情/.test(String(el.innerText||el.textContent||''))&&el.getBoundingClientRect().width>=280); }''')
                if state: break
            return _ok('成员大厅表情面板已打开', {'button':scan,'panel_visible':state}) if state else _fail('点击表情按钮后未出现表情面板', {'button':scan})
        except Exception as exc: return _fail(f'打开成员大厅表情面板失败: {str(exc)[:200]}')

    async def close_hall_emoji_panel(self, step) -> ActionResult:
        try:
            scan=await self.page.evaluate(r'''() => { const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&r.bottom>0&&r.top<innerHeight;}; const image=Array.from(document.querySelectorAll('img.window-emoji')).find(visible); if(!image)return {panel:false}; let panel=image; for(let i=0;panel&&i<6;i+=1,panel=panel.parentElement){const r=panel.getBoundingClientRect();if(r.width>=280&&r.height>=160)break;} const r=panel?.getBoundingClientRect(); if(!r)return {panel:true}; const x=Math.min(innerWidth-120, Math.max(r.right+80, innerWidth*.62)); const y=Math.max(120, Math.min(innerHeight-160, r.top+50)); return {panel:true,outside:{x:Math.round(x),y:Math.round(y)}}; }''')
            if not scan.get('panel'): return _ok('成员大厅表情面板已处于关闭状态', scan)
            await self.page.mouse.click(scan['outside']['x'], scan['outside']['y'])
            await asyncio.sleep(0.3)
            visible=await self.page.evaluate(r'''() => Array.from(document.querySelectorAll('img.window-emoji')).some(el=>{const r=el.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight;})''')
            return _ok('成员大厅表情面板已关闭') if not visible else _fail('再次点击表情按钮后面板仍可见')
        except Exception as exc: return _fail(f'关闭成员大厅表情面板失败: {str(exc)[:200]}')

    async def select_hall_emoji(self, step) -> ActionResult:
        try:
            scan=await self.page.evaluate(r'''() => { const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&r.bottom>0&&r.top<innerHeight;}; const panel=Array.from(document.querySelectorAll('div')).filter(el=>{const r=el.getBoundingClientRect();return visible(el)&&/自定义表情/.test(String(el.innerText||el.textContent||''))&&r.width>=280&&r.width<=900&&r.height>=160&&r.height<=700;}).sort((a,b)=>a.getBoundingClientRect().width-b.getBoundingClientRect().width)[0]; const target=(panel?Array.from(panel.querySelectorAll('img')).filter(visible):[]).find(el=>{const r=el.getBoundingClientRect();return r.width>=24&&r.width<=160&&r.height>=24&&r.height<=160;})||Array.from(document.querySelectorAll('img.window-emoji')).find(visible); if(!target)return {found:false}; const token='ai-hall-emoji-item-'+Date.now(); target.setAttribute('data-ai-hall-emoji-item',token); return {found:true,selector:'[data-ai-hall-emoji-item="'+token+'"]',src:target.getAttribute('src')||''}; }''')
            if not scan.get('found'):
                opened=await self.open_hall_emoji_panel(step)
                if opened.get('status') != 'completed': return opened
                scan=await self.page.evaluate(r'''() => { const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&r.bottom>0&&r.top<innerHeight;}; const panel=Array.from(document.querySelectorAll('div')).filter(el=>{const r=el.getBoundingClientRect();return visible(el)&&/自定义表情/.test(String(el.innerText||el.textContent||''))&&r.width>=280&&r.width<=900&&r.height>=160&&r.height<=700;}).sort((a,b)=>a.getBoundingClientRect().width-b.getBoundingClientRect().width)[0]; const target=(panel?Array.from(panel.querySelectorAll('img')).filter(visible):[]).find(el=>{const r=el.getBoundingClientRect();return r.width>=24&&r.width<=160&&r.height>=24&&r.height<=160;})||Array.from(document.querySelectorAll('img.window-emoji')).find(visible); if(!target)return {found:false}; const token='ai-hall-emoji-item-'+Date.now(); target.setAttribute('data-ai-hall-emoji-item',token); return {found:true,selector:'[data-ai-hall-emoji-item="'+token+'"]',src:target.getAttribute('src')||''}; }''')
            if not scan.get('found'): return _fail('表情面板内没有可选择的表情或贴纸', scan)
            await self.page.locator(scan['selector']).click(timeout=5000)
            await asyncio.sleep(0.3)
            await self._hall_set_context(emoji=scan.get('src',''))
            return _ok('已选择成员大厅表情', scan)
        except Exception as exc: return _fail(f'选择成员大厅表情失败: {str(exc)[:200]}')

    async def send_selected_hall_emoji(self, step) -> ActionResult:
        context=await self._hall_context(); src=context.get('emoji','')
        if not src: return _fail('发送表情前未记录已选择的表情')
        composer=await self._hall_composer()
        if composer.get('status') != 'completed': return composer
        try:
            # The same custom emoji can be present in prior messages. Snapshot
            # those nodes first so this run keeps an identity for its own bubble.
            before=await self.page.evaluate(r'''src => {
                const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&r.bottom>0&&r.top<innerHeight;};
                const own=el=>{const r=el.getBoundingClientRect();return r.left>innerWidth*.45&&r.top>120&&r.bottom<innerHeight-60;};
                let count=0;
                for(const image of Array.from(document.querySelectorAll('img')).filter(visible).filter(own)) {
                    if(String(image.getAttribute('src')||'')===src) { image.setAttribute('data-ai-hall-emoji-before','1'); count+=1; }
                }
                return {count};
            }''', src)
            await self.page.locator(composer['element']['selector']).press('Enter', timeout=8000)
            for _ in range(12):
                await asyncio.sleep(0.4)
                identity=await self.page.evaluate(r'''src => {
                    const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&r.bottom>0&&r.top<innerHeight;};
                    const own=el=>{const r=el.getBoundingClientRect();return r.left>innerWidth*.45&&r.top>120&&r.bottom<innerHeight-60;};
                    const image=Array.from(document.querySelectorAll('img')).filter(visible).filter(own).filter(el=>String(el.getAttribute('src')||'')===src&&!el.hasAttribute('data-ai-hall-emoji-before')).sort((a,b)=>b.getBoundingClientRect().top-a.getBoundingClientRect().top)[0];
                    if(!image)return {found:false};
                    const token='ai-hall-emoji-message-'+Date.now()+'-'+Math.random().toString(36).slice(2);
                    image.setAttribute('data-ai-hall-message-token',token);
                    const r=image.getBoundingClientRect();
                    return {found:true,token,rect:{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)}};
                }''', src)
                if identity.get('found'):
                    await self._hall_set_context(emoji_message_token=identity['token'])
                    return _ok('成员大厅表情消息已发送', {'emoji_src':src,'before':before,'identity':identity})
            return _fail('发送后消息流未出现本次表情消息', {'emoji_src':src,'before':before})
        except Exception as exc: return _fail(f'发送成员大厅表情失败: {str(exc)[:200]}')

    async def close_hall_top_ad(self, step) -> ActionResult:
        try:
            scan=await self.page.evaluate(r'''() => { const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&r.bottom>0&&r.top<innerHeight;}; const all=Array.from(document.querySelectorAll('button,[role="button"],i,svg,span,div')).filter(visible); const target=all.find(el=>{const r=el.getBoundingClientRect(),t=String(el.innerText||el.textContent||el.getAttribute('aria-label')||'').replace(/\s+/g,''),c=String(el.className||'')+' '+String(el.getAttribute('aria-label')||''); return r.left>innerWidth*.82&&r.top>80&&r.top<innerHeight*.5&&r.width<=48&&r.height<=48&&(/^(?:x|×|关闭)$/i.test(t)||/close/i.test(c));}); if(!target)return {found:false,skipped:true}; const token='ai-hall-ad-close-'+Date.now(); target.setAttribute('data-ai-hall-ad-close',token);return {found:true,selector:'[data-ai-hall-ad-close="'+token+'"]'}; }''')
            if scan.get('skipped'): return _ok('右上广告或关闭按钮不存在，按用例前置条件跳过', scan)
            await self.page.locator(scan['selector']).click(timeout=5000)
            return _ok('已关闭成员大厅右上广告', scan)
        except Exception as exc: return _fail(f'关闭成员大厅右上广告失败: {str(exc)[:200]}')

    async def close_hall_message_menus(self, step) -> ActionResult:
        """Dismiss transient message menus without touching message content."""
        try:
            await self.page.keyboard.press('Escape')
            await self.page.mouse.click(max(420, int((await self.page.evaluate('innerWidth')) * .48)), 220)
            await asyncio.sleep(0.25)
            open_menu=await self.page.evaluate(r'''() => {
                const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&r.bottom>0&&r.top<innerHeight;};
                const labels=['回复消息','复制消息','撤回消息','删除消息','无痕删除'];
                return Array.from(document.querySelectorAll('button,[role="button"],li,span,div')).filter(visible).some(el=>labels.includes(String(el.innerText||el.textContent||'').trim()));
            }''')
            return _ok('成员大厅消息操作菜单已关闭，未执行消息变更') if not open_menu else _fail('成员大厅消息操作菜单仍处于打开状态')
        except Exception as exc:
            return _fail(f'关闭成员大厅消息操作菜单失败: {str(exc)[:200]}')

    async def _hall_member_search_snapshot(self) -> Dict[str, Any]:
        return await self.page.evaluate(r'''() => {
            const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&r.bottom>0&&r.top<innerHeight;};
            const norm=value=>String(value||'').replace(/\s+/g,' ').trim();
            const input=Array.from(document.querySelectorAll('input')).filter(visible).filter(el=>{const r=el.getBoundingClientRect();return /搜索成员/.test(String(el.getAttribute('placeholder')||''))&&r.left>innerWidth*.72;})[0];
            if(!input)return {found:false};
            const ir=input.getBoundingClientRect();
            // The member panel is a virtualized right-side list.  Scanning the
            // whole page accidentally treats role badges (for example "高管")
            // and chat content as member names, so establish the panel scope
            // from the search input before reading rows.
            const panelCandidates=[];
            for(let node=input.parentElement,depth=0;node&&depth<10;node=node.parentElement,depth+=1){
                const r=node.getBoundingClientRect();
                if(visible(node)&&r.left>=innerWidth*.68&&r.width>=ir.width&&r.width<=innerWidth*.36&&r.height>=Math.max(180,ir.height+120)) panelCandidates.push({node,r});
            }
            const panel=(panelCandidates.sort((a,b)=>(a.r.width*a.r.height)-(b.r.width*b.r.height))[0]||{}).node||input.parentElement;
            const panelRect=panel.getBoundingClientRect();
            const ignored=/^(?:高级|在线|离线|管理员|成员|搜索成员|高管|群主|房主|主播|队长|版主|会长|管理)$/;
            const leaves=Array.from(panel.querySelectorAll('div,span,p,a')).filter(visible).map(el=>{
                const r=el.getBoundingClientRect(),text=norm(el.innerText||el.textContent);
                return {text,r,el};
            }).filter(item=>item.r.left>=panelRect.left+18&&item.r.right<=panelRect.right-4&&item.r.top>ir.bottom+6&&item.r.height<=42&&item.r.width<=Math.min(230,panelRect.width-18)&&item.text.length>=2&&item.text.length<=80&&!ignored.test(item.text)&&!/^(?:\d+|\d+\/\d+)$/.test(item.text));
            const names=[...new Set(leaves.sort((a,b)=>a.r.top-b.r.top).map(item=>item.text))].slice(0,40);
            // The list renders its empty state inside the same panel. Keep it
            // separate from member rows so negative-search assertions do not
            // accidentally validate the empty-state copy as a member name.
            const emptyStateItem=leaves.find(item=>item.text==='暂无搜索结果');
            const emptyState=Boolean(emptyStateItem);
            const emptyStateRect=emptyStateItem ? emptyStateItem.r : null;
            const emptyStateInPanel=Boolean(emptyStateRect)
                && emptyStateRect.left>=panelRect.left
                && emptyStateRect.right<=panelRect.right
                && emptyStateRect.top>=ir.bottom
                && emptyStateRect.bottom<=panelRect.bottom
                && panelRect.left>=innerWidth*.68;
            const loaders=Array.from(panel.querySelectorAll('[aria-busy="true"],[class*="loading" i],[class*="spinner" i],[class*="skeleton" i],[class*="pending" i]')).filter(visible);
            return {
                found:true,
                selector:null,
                value:input.value||'',
                rect:{x:Math.round(ir.x),y:Math.round(ir.y),w:Math.round(ir.width),h:Math.round(ir.height)},
                panel:{x:Math.round(panelRect.x),y:Math.round(panelRect.y),w:Math.round(panelRect.width),h:Math.round(panelRect.height)},
                loading:loaders.length>0,
                names,
                empty_state:emptyState,
                empty_state_in_panel:emptyStateInPanel,
                empty_state_rect:emptyStateRect ? {x:Math.round(emptyStateRect.x),y:Math.round(emptyStateRect.y),w:Math.round(emptyStateRect.width),h:Math.round(emptyStateRect.height)} : null,
                signature:names.join('|'),
            };
        }''')

    async def search_hall_member(self, step) -> ActionResult:
        try:
            before=await self._hall_member_search_snapshot()
            if not before.get('found'):
                return _fail('未找到成员大厅右侧“搜索成员”输入框', before)
            # The hall shell and its right member list are rendered separately.
            # Wait for actual member rows instead of treating the brief empty
            # interval immediately after navigation as a business empty state.
            for _ in range(48):
                if before.get('names') and not before.get('empty_state'):
                    break
                await asyncio.sleep(0.25)
                before=await self._hall_member_search_snapshot()
                if not before.get('found'):
                    return _fail('成员列表加载期间“搜索成员”输入框消失', before)
            names=before.get('names') or []
            if not names:
                return _fail('等待右侧成员列表加载后仍未找到可用于搜索的成员昵称', before)
            full_name=str(names[0]).strip()
            mode=str(step.get('search_mode') or 'full_name')
            requested_keyword=str(step.get('input_value') or step.get('search_keyword') or '').strip()
            keyword=requested_keyword or (full_name if mode=='full_name' else full_name[:min(2, len(full_name))])
            locator=self.page.locator('input[placeholder*="搜索成员"]').filter(has_not=self.page.locator('[disabled]')).last
            await locator.fill(keyword, timeout=8000)
            # NN filters on the input event. Enter is still useful on older
            # builds, but must not be used as evidence that async list data is
            # already rendered.
            await locator.press('Enter', timeout=5000)
            stable_rounds=0
            last_signature=None
            for _ in range(48):
                await asyncio.sleep(0.25)
                after=await self._hall_member_search_snapshot()
                if after.get('value')!=keyword or after.get('loading'):
                    stable_rounds=0
                    last_signature=None
                    continue
                signature=after.get('signature') or ''
                if signature==last_signature:
                    stable_rounds+=1
                else:
                    stable_rounds=0
                    last_signature=signature
                if stable_rounds>=2:
                    break
            else:
                after=await self._hall_member_search_snapshot()
            filtered=after.get('names') or []
            actual_value=str(after.get('value') or '')
            truncated_empty_keyword = keyword.startswith('NO_MEMBER_') and actual_value and keyword.startswith(actual_value)
            if actual_value != keyword and not truncated_empty_keyword:
                return _fail('成员搜索框未保留本次输入关键字', {'before':before,'after':after,'keyword':keyword})
            if after.get('loading'):
                return _fail('成员搜索结果持续加载未完成', {'before':before,'after':after,'keyword':keyword})
            # A no-result state is a valid outcome for dedicated negative and
            # special-character cases. Preserve it for their following
            # assertions instead of failing the input action itself.
            if after.get('empty_state'):
                if not after.get('empty_state_in_panel'):
                    return _fail('成员搜索空结果未限制在右侧成员列表区域', {'keyword':keyword, 'after':after})
                await self._hall_set_context(
                    member_search_keyword=keyword,
                    member_full_count=str(len(names)),
                    member_filtered_count='0',
                    member_search_empty='true',
                    member_search_empty_layout='true',
                )
                return _ok('右侧成员搜索已稳定展示空结果', {'keyword':keyword,'actual_value':actual_value,'truncated':truncated_empty_keyword,'before_count':len(names),'filtered_names':[], 'empty_state_rect':after.get('empty_state_rect'), 'panel':after.get('panel')})
            if not filtered:
                return _fail('成员搜索加载完成但未展示匹配成员', {'before':before,'after':after,'keyword':keyword})
            if not filtered or any(keyword not in name for name in filtered):
                return _fail('成员搜索结果未按关键字精确筛选', {'before':before,'after':after,'keyword':keyword})
            await self._hall_set_context(member_search_keyword=keyword, member_full_count=str(len(names)), member_filtered_count=str(len(filtered)))
            return _ok('右侧成员搜索已按昵称精确筛选', {'keyword':keyword,'before_count':len(names),'filtered_names':filtered})
        except Exception as exc:
            return _fail(f'成员大厅右侧成员搜索失败: {str(exc)[:200]}')

    async def verify_hall_member_search(self, step) -> ActionResult:
        """Validate member-search results inside the right member panel only."""
        try:
            snapshot=await self._hall_member_search_snapshot()
            if not snapshot.get('found'):
                return _fail('未找到成员大厅右侧“搜索成员”输入框', snapshot)
            record_id=getattr(self.execution_record, 'id', None)
            context=HALL_RUNTIME_CONTEXTS.get(record_id, {}) if record_id else {}
            expected=str(
                step.get('input_value')
                or step.get('search_keyword')
                or context.get('member_search_keyword')
                or snapshot.get('value')
                or ''
            ).strip()
            names=snapshot.get('names') or []
            actual_value=str(snapshot.get('value') or '')
            min_count=max(1, int(step.get('min_count') or 1))
            # The input being empty means this is a restoration assertion after
            # clearing a prior search. It must not reuse the old search keyword.
            if not actual_value:
                if snapshot.get('loading'):
                    return _fail('成员列表恢复时仍在加载，不能提前断言', {'snapshot':snapshot})
                if snapshot.get('empty_state') or len(names)<min_count:
                    return _fail('清空成员搜索后列表未恢复到要求数量', {'required_count':min_count, 'actual_count':len(names), 'snapshot':snapshot})
                return _ok('清空成员搜索后右侧成员列表已恢复', {'required_count':min_count, 'actual_count':len(names), 'names':names, 'panel':snapshot.get('panel')})
            if not expected:
                return _fail('成员搜索断言缺少当前搜索关键字', {'snapshot': snapshot, 'context': context})
            truncated_empty_keyword = expected.startswith('NO_MEMBER_') and actual_value and expected.startswith(actual_value)
            if actual_value != expected and not truncated_empty_keyword:
                return _fail('成员搜索框当前值与本次关键字不一致', {'expected':expected, 'snapshot':snapshot})
            if snapshot.get('loading'):
                return _fail('成员搜索结果仍在加载，不能提前断言', {'expected':expected, 'snapshot':snapshot})
            if snapshot.get('empty_state'):
                await self._hall_set_context(member_search_keyword=expected, member_filtered_count='0', member_search_empty='true')
                return _ok('右侧成员搜索已稳定展示空结果，且未保留成员条目', {'expected':expected, 'actual_value':actual_value, 'truncated':truncated_empty_keyword, 'panel':snapshot.get('panel')})
            if not names:
                return _fail('成员搜索结果为空，未找到匹配成员条目', {'expected':expected, 'snapshot':snapshot})
            mismatches=[name for name in names if expected not in name]
            if mismatches:
                return _fail('成员搜索结果包含不匹配的昵称', {'expected':expected, 'names':names, 'mismatches':mismatches, 'snapshot':snapshot})
            return _ok('右侧成员搜索结果均为匹配昵称', {'expected':expected, 'names':names, 'panel':snapshot.get('panel')})
        except Exception as exc:
            return _fail(f'验证成员大厅搜索结果失败: {str(exc)[:200]}')

    async def verify_hall_member_empty_state_layout(self, step) -> ActionResult:
        """Confirm that a prior negative member search kept its empty state scoped."""
        try:
            record_id=getattr(self.execution_record, 'id', None)
            context=HALL_RUNTIME_CONTEXTS.get(record_id, {}) if record_id else {}
            snapshot=await self._hall_member_search_snapshot()
            if not snapshot.get('found'):
                return _fail('未找到成员大厅右侧“搜索成员”输入框', snapshot)
            if snapshot.get('empty_state'):
                if not snapshot.get('empty_state_in_panel'):
                    return _fail('成员搜索空结果未限制在右侧成员列表区域', {'snapshot':snapshot})
                await self._hall_set_context(member_search_empty='true', member_search_empty_layout='true')
                return _ok('成员搜索空结果仅展示在右侧成员列表区域', {'empty_state_rect':snapshot.get('empty_state_rect'), 'panel':snapshot.get('panel')})
            if context.get('member_search_empty')=='true' and context.get('member_search_empty_layout')=='true':
                return _ok('成员搜索空结果展示时已验证其仅位于右侧成员列表区域', {'panel':snapshot.get('panel')})
            return _fail('未观察到可验证的成员搜索空结果状态', {'snapshot':snapshot, 'context':context})
        except Exception as exc:
            return _fail(f'验证成员搜索空结果布局失败: {str(exc)[:200]}')

    async def verify_hall_route(self, step) -> ActionResult:
        """Assert the stable route contract for the member hall without AI vision."""
        try:
            evidence = await self.page.evaluate(r'''() => {
                const app = document.querySelector('#app');
                const text = String((app && (app.innerText || app.textContent)) || '').replace(/\s+/g, ' ').trim();
                return {
                    url: location.href,
                    pathname: location.pathname,
                    appMounted: Boolean(app),
                    hasHallAnchor: /成员大厅|全员大厅/.test(text),
                };
            }''')
            on_hall_route = str(evidence.get('pathname') or '').rstrip('/') == '/community/7520/hall'
            if not on_hall_route:
                return _fail('成员搜索后已跳离成员大厅路由', evidence)
            if not evidence.get('appMounted') or not evidence.get('hasHallAnchor'):
                return _fail('成员大厅路由已打开但页面主体尚未完成渲染', evidence)
            return _ok('成员搜索后仍停留在成员大厅，页面主体正常渲染', evidence)
        except Exception as exc:
            return _fail(f'验证成员大厅路由失败: {str(exc)[:200]}')

    async def verify_hall_member_search_layout_health(self, step) -> ActionResult:
        """Verify real member-panel geometry after search without visual-model guesses."""
        try:
            scan_script = r'''() => {
                const visible = el => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight
                        && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
                };
                const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
                const inputs = Array.from(document.querySelectorAll('input')).filter(visible).filter(el => {
                    const r = el.getBoundingClientRect();
                    return /搜索成员/.test(String(el.getAttribute('placeholder') || '')) && r.left > innerWidth * .68;
                });
                const input = inputs[0];
                const app = document.querySelector('#app');
                const appText = norm(app && (app.innerText || app.textContent));
                const candidatePanels = [];
                if (input) {
                    const ir = input.getBoundingClientRect();
                    for (let node = input.parentElement, depth = 0; node && depth < 10; node = node.parentElement, depth += 1) {
                        const r = node.getBoundingClientRect();
                        if (visible(node) && r.left >= innerWidth * .68 && r.width >= ir.width
                            && r.width <= innerWidth * .36 && r.height >= Math.max(180, ir.height + 120)) {
                            candidatePanels.push({node, r});
                        }
                    }
                }
                const panel = (candidatePanels.sort((a, b) => (a.r.width * a.r.height) - (b.r.width * b.r.height))[0] || {}).node;
                const panelRect = panel && panel.getBoundingClientRect();
                const overflowChildren = panel ? Array.from(panel.querySelectorAll('*')).filter(visible).map(el => {
                    const r = el.getBoundingClientRect();
                    return {tag: el.tagName.toLowerCase(), text: norm(el.innerText || el.textContent).slice(0, 80), left: r.left, right: r.right, top: r.top, bottom: r.bottom};
                }).filter(item => item.top >= panelRect.top - 1 && item.bottom <= panelRect.bottom + 1
                    && item.right > panelRect.right + 2 && item.left < panelRect.right - 2).slice(0, 8) : [];
                const fullScreenLoaders = Array.from(document.querySelectorAll(
                    '[aria-busy="true"], [role="progressbar"], [class*="loading" i], [class*="spinner" i], [class*="skeleton" i], [class*="pending" i]'
                )).filter(visible).map(el => {
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return {tag: el.tagName.toLowerCase(), className: String(el.className || '').slice(0, 160), position: s.position, width: r.width, height: r.height};
                }).filter(item => item.width >= innerWidth * .72 && item.height >= innerHeight * .48);
                return {
                    appMounted: Boolean(app),
                    appTextLength: appText.length,
                    searchInputFound: Boolean(input),
                    panelFound: Boolean(panel),
                    panel: panelRect ? {
                        x: Math.round(panelRect.x), y: Math.round(panelRect.y), w: Math.round(panelRect.width), h: Math.round(panelRect.height),
                        right: Math.round(panelRect.right), scrollWidth: panel.scrollWidth, clientWidth: panel.clientWidth,
                    } : null,
                    panelInViewport: Boolean(panelRect) && panelRect.left >= innerWidth * .68 && panelRect.right <= innerWidth + 2,
                    horizontalScroll: Boolean(panel) && panel.scrollWidth > panel.clientWidth + 2,
                    overflowChildren,
                    fullScreenLoaders,
                    viewport: {width: innerWidth, height: innerHeight},
                };
            }'''
            samples = []
            # The hall list is independently hydrated.  A single DOM sample
            # can catch its brief mount phase and turn a healthy page into a
            # false failure.  Require two consecutive healthy samples instead.
            for attempt in range(8):
                evidence = await self.page.evaluate(scan_script)
                healthy = (
                    bool(evidence.get('appMounted'))
                    and int(evidence.get('appTextLength') or 0) >= 30
                    and bool(evidence.get('searchInputFound'))
                    and bool(evidence.get('panelFound'))
                    and bool(evidence.get('panelInViewport'))
                    and not evidence.get('fullScreenLoaders')
                    and not evidence.get('horizontalScroll')
                )
                samples.append({'healthy': healthy, **evidence})
                if len(samples) >= 2 and samples[-1]['healthy'] and samples[-2]['healthy']:
                    return _ok(
                        '成员搜索后页面正常渲染，未持续加载，右侧成员面板无真实横向溢出',
                        {'samples': samples[-2:]},
                    )
                if attempt < 7:
                    await asyncio.sleep(.5)
            last = samples[-1] if samples else {}
            if not last.get('appMounted') or int(last.get('appTextLength') or 0) < 30:
                reason = '页面主体持续未正常渲染，疑似白屏'
            elif not last.get('searchInputFound') or not last.get('panelFound'):
                reason = '右侧成员搜索区域持续未渲染'
            elif not last.get('panelInViewport'):
                reason = '右侧成员面板持续未完整位于当前视口内'
            elif last.get('fullScreenLoaders'):
                reason = '页面持续存在全屏加载遮罩'
            else:
                reason = '右侧成员面板存在真实横向滚动溢出'
            return _fail(reason, {'samples': samples})
        except Exception as exc:
            return _fail(f'验证成员搜索页面布局健康度失败: {str(exc)[:200]}')

    async def verify_hall_channel_controls(self, step) -> ActionResult:
        """Verify the stable, self-contained shell of a direct channel link."""
        try:
            scan_script = r'''() => {
                const visible = (el) => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
                };
                const text = (el) => String(el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
                const w = innerWidth, h = innerHeight;
                const inViewport = r => r.bottom > 0 && r.top < h && r.right > 0 && r.left < w;
                const nodes = Array.from(document.querySelectorAll('body *')).filter(visible).map(el => ({el, value:text(el), r:el.getBoundingClientRect()})).filter(item => inViewport(item.r));
                const roomHeaders = nodes.filter(item => item.r.top >= 110 && item.r.top <= 185 && item.r.left >= 350 && item.r.left < w * .72 && /(?:游戏)?语音房/.test(item.value) && item.value.length <= 120)
                    .map(item => ({text:item.value, rect:{x:Math.round(item.r.x), y:Math.round(item.r.y), w:Math.round(item.r.width), h:Math.round(item.r.height)}}));
                const onlineLabels = nodes.filter(item => item.r.left >= w * .78 && item.r.top >= 260 && item.r.top < h * .72 && /^在线\s*\d+/.test(item.value))
                    .map(item => ({text:item.value, rect:{x:Math.round(item.r.x), y:Math.round(item.r.y), w:Math.round(item.r.width), h:Math.round(item.r.height)}}));
                const rightAvatars = Array.from(document.querySelectorAll('img, [class*="avatar" i]')).filter(visible).map(el => ({tag:el.tagName.toLowerCase(), r:el.getBoundingClientRect()}))
                    .filter(item => inViewport(item.r) && item.r.left >= w * .78 && item.r.top >= 280 && item.r.top < h * .82 && item.r.width >= 18 && item.r.height >= 18)
                    .map(item => ({tag:item.tag, rect:{x:Math.round(item.r.x), y:Math.round(item.r.y), w:Math.round(item.r.width), h:Math.round(item.r.height)}}));
                const rightNames = nodes.filter(item => item.r.left >= w * .8 && item.r.top >= 300 && item.r.top < h * .82 && item.r.width <= w * .18 && item.value.length >= 2 && item.value.length <= 60 && !/^(?:在线\s*\d+|搜索|战绩信息|添加设置|未认证)$/.test(item.value))
                    .map(item => ({text:item.value, rect:{x:Math.round(item.r.x), y:Math.round(item.r.y), w:Math.round(item.r.width), h:Math.round(item.r.height)}}));
                const bottomControls = Array.from(document.querySelectorAll('button, [role="button"], a, svg')).filter(visible).map(el => {
                    const r = el.getBoundingClientRect();
                    return {tag:el.tagName.toLowerCase(), label:String(el.getAttribute('aria-label') || el.getAttribute('title') || text(el)).slice(0, 80), r};
                }).filter(item => inViewport(item.r) && item.r.left < Math.min(220, w * .16) && item.r.top > h - 100 && item.r.width >= 14 && item.r.height >= 14)
                    .map(item => ({tag:item.tag, label:item.label, rect:{x:Math.round(item.r.x), y:Math.round(item.r.y), w:Math.round(item.r.width), h:Math.round(item.r.height)}}));
                const bottomAvatars = Array.from(document.querySelectorAll('img, [class*="avatar" i]')).filter(visible).map(el => ({tag:el.tagName.toLowerCase(), r:el.getBoundingClientRect()}))
                    .filter(item => inViewport(item.r) && item.r.left < Math.min(130, w * .1) && item.r.top > h - 115 && item.r.width >= 18 && item.r.height >= 18)
                    .map(item => ({tag:item.tag, rect:{x:Math.round(item.r.x), y:Math.round(item.r.y), w:Math.round(item.r.width), h:Math.round(item.r.height)}}));
                return {url:location.href, viewport:{w,h}, roomHeaders, onlineLabels, rightAvatars, rightNames, bottomControls, bottomAvatars, appMounted:!!document.querySelector('#app')};
            }'''
            # A direct room URL mounts its static shell before the voice-room
            # payload and member panel arrive.  Wait for the complete visual
            # contract instead of treating a single fixed delay as readiness.
            evidence = {}
            for attempt in range(2):
                deadline = time.monotonic() + 20
                while True:
                    evidence = await self.page.evaluate(scan_script)
                    room_ready = bool(evidence.get('roomHeaders'))
                    members_ready = bool(evidence.get('onlineLabels') and evidence.get('rightAvatars') and evidence.get('rightNames'))
                    controls_ready = bool(evidence.get('bottomAvatars')) and len(evidence.get('bottomControls') or []) >= 2
                    if room_ready and members_ready and controls_ready:
                        break
                    if time.monotonic() >= deadline:
                        break
                    await asyncio.sleep(.4)
                if room_ready and members_ready and controls_ready:
                    break
                # Direct room routes can mount their SPA shell without the
                # realtime handshake. Reconnect once before reporting a real
                # unavailable-member failure.
                if attempt == 0:
                    await self.page.reload(wait_until='domcontentloaded', timeout=20000)
                    await asyncio.sleep(.8)
            channel_route='/community/7520/channel/' in str(evidence.get('url') or '')
            if not channel_route:
                return _fail('未停留在目标语音房路由', evidence)
            if not evidence.get('roomHeaders'):
                return _fail('未读取到目标语音房标题及人数/容量状态', evidence)
            if not evidence.get('onlineLabels') or not evidence.get('rightAvatars') or not evidence.get('rightNames'):
                header_text = ' '.join(item.get('text', '') for item in evidence.get('roomHeaders') or [])
                # Capacity separators are SVG icons in some NN builds, so
                # innerText can be either "0/00" or the equivalent "0 00".
                empty_capacity = re.search(r'\b0\s*(?:/\s*)?0+\b', header_text)
                if empty_capacity and not evidence.get('rightAvatars') and not evidence.get('rightNames'):
                    if not evidence.get('bottomAvatars') or len(evidence.get('bottomControls') or []) < 2:
                        return _fail('空房态下底部账号或语音控制未正常展示', evidence)
                    return _ok('目标语音房为空，已确认空成员态和底部语音控制布局正常', evidence)
                return _fail('未检测到右侧在线成员的头像与昵称条目', evidence)
            if not evidence.get('bottomAvatars'):
                return _fail('未检测到页面左下角当前账号头像', evidence)
            if len(evidence.get('bottomControls') or []) < 2:
                return _fail('未检测到至少两个独立的底部语音控制', evidence)
            return _ok('语音房人数状态及底部账号、语音控制布局正常', evidence)
        except Exception as exc:
            return _fail(f'验证语音房基础布局失败: {str(exc)[:200]}')

    async def clear_hall_member_search(self, step) -> ActionResult:
        try:
            record_id=getattr(self.execution_record, 'id', None)
            cached=HALL_RUNTIME_CONTEXTS.get(record_id, {}) if record_id else {}
            before=await self._hall_member_search_snapshot()
            if not before.get('found'):
                return _fail('未找到成员大厅右侧“搜索成员”输入框', before)
            locator=self.page.locator('input[placeholder*="搜索成员"]').filter(has_not=self.page.locator('[disabled]')).last
            await locator.fill('', timeout=8000)
            required_count=max(1, int(cached.get('member_full_count') or cached.get('member_filtered_count') or 0))
            for _ in range(48):
                await asyncio.sleep(0.25)
                after=await self._hall_member_search_snapshot()
                if after.get('value')=='' and not after.get('empty_state') and len(after.get('names') or [])>=required_count:
                    break
            else:
                after=await self._hall_member_search_snapshot()
            restored=after.get('names') or []
            required_count=max(1, int(cached.get('member_full_count') or cached.get('member_filtered_count') or 0))
            if after.get('value')!='' or after.get('empty_state') or len(restored)<required_count:
                return _fail('清空成员搜索后列表未恢复', {'before':before,'after':after,'required_count':required_count})
            return _ok('已清空右侧成员搜索，成员列表恢复展示', {'restored_count':len(restored),'required_count':required_count})
        except Exception as exc:
            return _fail(f'清空成员大厅右侧成员搜索失败: {str(exc)[:200]}')

    async def _open_hall_message_menu(self, value: str = '', emoji_src: str = '', message_token: str = '') -> ActionResult:
        if not value and not emoji_src:
            return _fail('消息操作缺少本次运行的唯一消息标识')
        try:
            await self.page.evaluate(r'''() => { const scroller=document.querySelector('.msg-common-scroll'); if(scroller) scroller.scrollTop=0; }''')
            await asyncio.sleep(0.2)
            context=await self._hall_context()
            scan=await self.page.evaluate(r'''payload => {
                const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&r.bottom>0&&r.top<innerHeight;};
                const inOwnMessageLane=el=>{const r=el.getBoundingClientRect();return r.left>innerWidth*.45&&r.top>120&&r.bottom<innerHeight-5;};
                const exact=payload.value ? Array.from(document.querySelectorAll('div,span,p')).filter(visible).filter(inOwnMessageLane).filter(el=>String(el.innerText||el.textContent||'').trim()===payload.value).sort((a,b)=>a.getBoundingClientRect().width-b.getBoundingClientRect().width)[0] : null;
                const marked=payload.message_token ? Array.from(document.querySelectorAll('[data-ai-hall-message-token]')).filter(visible).find(el=>el.getAttribute('data-ai-hall-message-token')===payload.message_token) : null;
                const emoji=!marked&&!exact&&payload.emoji_src ? Array.from(document.querySelectorAll('img')).filter(visible).filter(el=>String(el.getAttribute('src')||'')===payload.emoji_src&&!el.classList.contains('window-emoji'))[0] : null;
                const source=marked||exact||emoji;
                if(!source)return {found:false,reason:'消息流未找到本次运行消息'};
                if(marked) {
                    const rr=marked.getBoundingClientRect();
                    const token='ai-hall-message-row-'+Date.now();
                    marked.setAttribute('data-ai-hall-message-row',token);
                    return {found:true,selector:'[data-ai-hall-message-row="'+token+'"]',text:'emoji-message',rect:{x:Math.round(rr.x),y:Math.round(rr.y),w:Math.round(rr.width),h:Math.round(rr.height)}};
                }
                let row=source;
                for(let depth=0;row&&depth<10;depth+=1,row=row.parentElement){const r=row.getBoundingClientRect();if(r.width>=260&&r.height>=35&&r.height<=360&&r.left>300&&r.right<innerWidth-120)break;}
                if(!row)return {found:false,reason:'未找到唯一消息所属的消息单元'};
                const rr=row.getBoundingClientRect(); const token='ai-hall-message-row-'+Date.now(); row.setAttribute('data-ai-hall-message-row',token); return {found:true,selector:'[data-ai-hall-message-row="'+token+'"]',text:String(row.innerText||row.textContent||'').slice(0,300),rect:{x:Math.round(rr.x),y:Math.round(rr.y),w:Math.round(rr.width),h:Math.round(rr.height)}};
            }''', {'value':value,'emoji_src':emoji_src,'message_token':message_token or (context.get('emoji_message_token','') if emoji_src else '')})
            if not scan.get('found'): return _fail('打开成员大厅消息操作菜单失败', scan)
            # NN creates the action bar only after hovering the concrete
            # message row.  The old implementation guessed a fixed point to
            # the left of the bubble, which breaks as soon as the bubble width
            # or the toolbar placement changes.
            row=self.page.locator(scan['selector'])
            try:
                await row.hover(timeout=4000)
            except Exception:
                rect=scan.get('rect') or {}
                if not rect:
                    return _fail('消息单元内未找到操作菜单图标', {'row':scan})
                await self.page.mouse.move(rect['x']+rect['w']/2, rect['y']+rect['h']/2)
            await asyncio.sleep(0.35)
            trigger=await self.page.evaluate(r'''selector => {
                const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&r.bottom>0&&r.top<innerHeight;};
                const row=document.querySelector(selector); if(!row)return {found:false,reason:'消息单元在悬停后已被虚拟列表卸载'};
                const rr=row.getBoundingClientRect();
                const roots=[]; let current=row;
                for(let depth=0;current&&depth<7;depth+=1,current=current.parentElement) roots.push(current);
                const candidates=[];
                for(const root of roots){
                    for(const raw of Array.from(root.querySelectorAll('button,[role="button"],a,[aria-label],i,svg,[class*="more" i],[class*="menu" i],[class*="ellipsis" i],[class*="action" i],[class*="operation" i]'))){
                        if(!visible(raw)||raw===row||raw.contains(row))continue;
                        const el=raw.closest('button,[role="button"],a,[class*="cursor-pointer" i],[class*="clickable" i]')||raw;
                        if(!visible(el))continue;
                        const r=el.getBoundingClientRect();
                        const dx=Math.max(rr.left-r.right,r.left-rr.right,0),dy=Math.max(rr.top-r.bottom,r.top-rr.bottom,0);
                        if(dx>150||dy>110||r.width>180||r.height>80)continue;
                        const text=String(el.innerText||el.textContent||el.getAttribute('aria-label')||'').replace(/\s+/g,'');
                        const cls=String(el.className||'')+' '+String(raw.className||'')+' '+String(el.getAttribute('aria-label')||'');
                        let score=0;
                        if(/more|更多|菜单|操作|ellipsis|dots|three/i.test(cls))score+=5000;
                        if(/^(?:\.\.\.|…|更多|操作)$/.test(text))score+=4200;
                        if(el.tagName==='BUTTON'||el.getAttribute('role')==='button'||/cursor-pointer|clickable/i.test(cls))score+=1000;
                        if(r.left<rr.left&&r.right>=rr.left-110)score+=500;
                        if(r.right>rr.right&&r.left<=rr.right+110)score+=350;
                        if(score>=1000)candidates.push({el,r,text,cls,score});
                    }
                }
                const best=candidates.sort((a,b)=>b.score-a.score||a.r.width-b.r.width)[0];
                if(!best)return {found:false,reason:'悬停后未在本消息单元附近发现更多操作入口',row:{x:Math.round(rr.x),y:Math.round(rr.y),w:Math.round(rr.width),h:Math.round(rr.height)}};
                const token='ai-hall-message-menu-trigger-'+Date.now()+'-'+Math.random().toString(36).slice(2);
                best.el.setAttribute('data-ai-hall-message-menu-trigger',token);
                return {found:true,selector:'[data-ai-hall-message-menu-trigger="'+token+'"]',detail:{text:best.text,cls:best.cls.slice(0,180),rect:{x:Math.round(best.r.x),y:Math.round(best.r.y),w:Math.round(best.r.width),h:Math.round(best.r.height)}}};
            }''', scan['selector'])
            if not trigger.get('found'):
                return _fail('消息单元内未找到操作菜单图标', {'row':scan,'trigger':trigger})
            await self.page.locator(trigger['selector']).click(timeout=5000)
            await asyncio.sleep(0.35)
            menu_state=await self.page.evaluate(r'''() => { const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';}; const nodes=Array.from(document.querySelectorAll('button,[role="button"],li,span,div')).filter(visible); return {open:nodes.some(el=>/撤回|回复|删除/.test(String(el.innerText||el.textContent||'').trim()))}; }''')
            if not menu_state.get('open'):
                return _fail('点击消息操作入口后菜单未打开', {'row':scan,'trigger':trigger,'menu_state':menu_state})
            return _ok('已打开成员大厅消息操作菜单', {'row':scan,'trigger':trigger})
        except Exception as exc: return _fail(f'打开成员大厅消息操作菜单失败: {str(exc)[:200]}')

    async def _click_hall_menu_operation(self, operation: str) -> ActionResult:
        try:
            scan=await self.page.evaluate(r'''operation => { const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&r.bottom>0&&r.top<innerHeight;}; const nodes=Array.from(document.querySelectorAll('button,[role="button"],li,span,div')).filter(visible); const source=nodes.filter(el=>String(el.innerText||el.textContent||'').trim().includes(operation)).sort((a,b)=>a.getBoundingClientRect().width-b.getBoundingClientRect().width)[0]; if(!source)return {found:false}; const target=source.closest('button,[role="button"],[class*="menu" i],[class*="dropdown" i],[class*="cursor-pointer" i]')||source; const token='ai-hall-menu-operation-'+Date.now(); target.setAttribute('data-ai-hall-menu-operation',token); return {found:true,selector:'[data-ai-hall-menu-operation="'+token+'"]'}; }''', operation)
            if not scan.get('found'): return _fail(f'消息操作菜单中未找到“{operation}”', scan)
            await self.page.locator(scan['selector']).click(timeout=5000)
            await asyncio.sleep(0.35)
            return _ok(f'已点击成员大厅消息操作“{operation}”', scan)
        except Exception as exc: return _fail(f'点击成员大厅消息操作失败: {str(exc)[:200]}')

    async def retract_hall_runtime_message(self, step) -> ActionResult:
        context=await self._hall_context(); role=str(step.get('message_role') or 'last'); value=context.get('reply' if role=='reply' else ('original' if role=='original' else 'last'),'')
        emoji_src=context.get('emoji','') if role=='emoji' else ''
        message_token=context.get('emoji_message_token','') if role=='emoji' else context.get(f'{role}_message_token','')
        menu=await self._open_hall_message_menu(value, emoji_src, message_token)
        if menu.get('status')!='completed': return menu
        operation=await self._click_hall_menu_operation('撤回')
        if operation.get('status')!='completed': return operation
        await asyncio.sleep(0.5)
        exists=await self._hall_message_visible(value, emoji_src, message_token)
        if exists.get('found'): return _fail('撤回后本次唯一消息仍作为普通消息显示', {'value':value,'evidence':exists})
        return _ok('已撤回本次成员大厅测试消息', {'value':value,'emoji_src':emoji_src})

    async def _hall_invite_share_panel_state(self) -> Dict[str, Any]:
        """Find the invite/share overlay without confusing it with global navigation."""
        return await self.page.evaluate(r'''() => {
            const visible = el => {
                const r = el.getBoundingClientRect(), s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
            };
            const norm = value => String(value || '').replace(/\s+/g, '').trim();
            const markers = /邀请好友|邀请.*加入|复制链接|分享至|二维码/;
            const leaves = Array.from(document.querySelectorAll('div,span,p,h1,h2,h3')).filter(visible)
                .filter(el => markers.test(norm(el.innerText || el.textContent || '')));
            const candidates = [];
            for (const leaf of leaves) {
                for (let root = leaf; root && root !== document.body; root = root.parentElement) {
                    const r = root.getBoundingClientRect();
                    if (!visible(root) || r.width < 220 || r.height < 100 || r.width > innerWidth * .85 || r.height > innerHeight * .9) continue;
                    const text = norm(root.innerText || root.textContent || '');
                    if (!markers.test(text)) continue;
                    const cls = String(root.className || '');
                    let score = 0;
                    if (/dialog|modal|popover|popup|drawer/i.test(cls) || root.getAttribute('role') === 'dialog') score += 1600;
                    if (r.left > innerWidth * .08 && r.right < innerWidth * .92) score += 500;
                    score += Math.min(text.length, 160);
                    candidates.push({r, text, cls, score});
                    break;
                }
            }
            const best = candidates.sort((a, b) => b.score - a.score)[0];
            return best ? {
                open: true,
                text: best.text.slice(0, 500),
                cls: best.cls.slice(0, 180),
                rect: {x: Math.round(best.r.x), y: Math.round(best.r.y), w: Math.round(best.r.width), h: Math.round(best.r.height)},
            } : {open: false};
        }''')

    async def open_hall_invite_share(self, step) -> ActionResult:
        """Open the hall-specific invite control and prove that an overlay appeared."""
        try:
            scan = await self.page.evaluate(r'''() => {
                const visible = el => {
                    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
                };
                const norm = value => String(value || '').replace(/\s+/g, '').trim();
                const sources = Array.from(document.querySelectorAll('button,[role="button"],a,div,span')).filter(visible)
                    .filter(el => norm(el.innerText || el.textContent || el.getAttribute('aria-label')) === '邀请/分享')
                    .map(source => {
                        const target = source.closest('button,[role="button"],a,[class*="cursor-pointer" i]') || source;
                        const r = target.getBoundingClientRect();
                        const inHallHeader = r.top >= 70 && r.top <= 220 && r.left > innerWidth * .12 && r.left < innerWidth * .65;
                        return {target, r, inHallHeader};
                    })
                    .filter(item => item.inHallHeader)
                    .sort((a, b) => a.r.width * a.r.height - b.r.width * b.r.height);
                const best = sources[0];
                if (!best) return {found: false};
                const token = 'ai-hall-invite-share-' + Date.now() + '-' + Math.random().toString(36).slice(2);
                best.target.setAttribute('data-ai-hall-invite-share', token);
                return {found: true, selector: '[data-ai-hall-invite-share="' + token + '"]', rect: {x: Math.round(best.r.x), y: Math.round(best.r.y), w: Math.round(best.r.width), h: Math.round(best.r.height)}};
            }''')
            if not scan.get('found'):
                return _fail('未找到成员大厅顶部“邀请/分享”入口', scan)
            await self.page.locator(scan['selector']).click(timeout=5000)
            state = {}
            for _ in range(16):
                await asyncio.sleep(0.25)
                state = await self._hall_invite_share_panel_state()
                if state.get('open'):
                    return _ok('已打开成员大厅邀请分享面板', {'trigger': scan, 'panel': state})
            return _fail('点击“邀请/分享”后未出现邀请分享面板', {'trigger': scan, 'panel': state})
        except Exception as exc:
            return _fail(f'打开成员大厅邀请分享面板失败: {str(exc)[:200]}')

    async def close_hall_invite_share(self, step) -> ActionResult:
        """Close only the active invite/share overlay and verify the underlying hall remains."""
        try:
            scan = await self.page.evaluate(r'''() => {
                const visible = el => {
                    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
                };
                const norm = value => String(value || '').replace(/\s+/g, '').trim();
                const markers = /邀请好友|邀请.*加入|复制链接|分享至|二维码/;
                const modalRoots = Array.from(document.querySelectorAll('[role="dialog"],.ui-dialog,.nn-dialog,.nn-modal,.modal,.dialog,[class*="modal" i],[class*="dialog" i]'))
                    .filter(visible)
                    .filter(el => markers.test(norm(el.innerText || el.textContent || '')))
                    .filter(el => {
                        const r = el.getBoundingClientRect();
                        return r.width >= 220 && r.height >= 100 && r.width <= innerWidth * .85 && r.height <= innerHeight * .9;
                    })
                    .sort((a, b) => (a.getBoundingClientRect().width * a.getBoundingClientRect().height) - (b.getBoundingClientRect().width * b.getBoundingClientRect().height));
                let root = modalRoots[0] || null;
                if (!root) {
                    const marker = Array.from(document.querySelectorAll('div,span,p,h1,h2,h3')).filter(visible)
                        .find(el => markers.test(norm(el.innerText || el.textContent || '')));
                    if (!marker) return {found: false, reason: '邀请分享面板未打开'};
                    root = marker;
                    for (; root && root !== document.body; root = root.parentElement) {
                        const r = root.getBoundingClientRect();
                        if (visible(root) && r.width >= 220 && r.height >= 100 && r.width <= innerWidth * .85 && r.height <= innerHeight * .9) break;
                    }
                }
                if (!root || root === document.body) return {found: false, reason: '未识别邀请分享面板容器'};
                const rr = root.getBoundingClientRect();
                const candidates = Array.from(root.querySelectorAll('button,[role="button"],[aria-label],svg,i,span,div')).filter(visible)
                    .map(el => {
                        const r = el.getBoundingClientRect();
                        const text = norm(el.innerText || el.textContent || el.getAttribute('aria-label'));
                        const cls = String(el.className || '') + ' ' + String(el.getAttribute('aria-label') || '');
                        const closeMark = /^(关闭|close|x|×|✕|✖)$/i.test(text) || /close|dismiss/i.test(cls);
                        const topRight = r.left >= rr.right - 90 && r.top <= rr.top + 90 && r.width <= 80 && r.height <= 80;
                        return {el, r, score: (closeMark ? 5000 : 0) + (topRight ? 1800 : 0)};
                    })
                    .filter(item => item.score >= 5000 || (item.score >= 1800 && item.r.width <= 48 && item.r.height <= 48))
                    .sort((a, b) => b.score - a.score);
                const best = candidates[0];
                if (!best) return {found: false, reason: '邀请分享面板未找到右上角关闭入口'};
                const token = 'ai-hall-invite-share-close-' + Date.now();
                best.el.setAttribute('data-ai-hall-invite-share-close', token);
                return {found: true, selector: '[data-ai-hall-invite-share-close="' + token + '"]'};
            }''')
            if not scan.get('found'):
                return _fail('关闭成员大厅邀请分享面板失败', scan)
            await self.page.locator(scan['selector']).click(timeout=5000)
            for _ in range(16):
                await asyncio.sleep(0.25)
                if not (await self._hall_invite_share_panel_state()).get('open'):
                    hall = await self.page.evaluate(r'''() => location.pathname.endsWith('/hall') && !!document.querySelector('[contenteditable]')''')
                    return _ok('已关闭邀请分享面板并恢复成员大厅', {'close': scan, 'hall_ready': hall}) if hall else _fail('邀请分享面板已关闭，但成员大厅输入区未恢复', {'close': scan})
            return _fail('点击关闭后邀请分享面板仍可见', {'close': scan})
        except Exception as exc:
            return _fail(f'关闭成员大厅邀请分享面板失败: {str(exc)[:200]}')

    async def verify_hall_retract_notice(self, step) -> ActionResult:
        """Verify the system-generated recall notice created by this independent run."""
        try:
            notice = await self.page.evaluate(r'''() => {
                const visible = el => {
                    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && r.bottom > 0 && r.top < innerHeight;
                };
                const textPattern = /(?:你|您)撤回了?一条消息|消息已撤回/;
                const nodes = Array.from(document.querySelectorAll('div,span,p')).filter(visible)
                    .filter(el => textPattern.test(String(el.innerText || el.textContent || '').replace(/\s+/g, '')))
                    .map(source => {
                        let row = source;
                        for (let depth = 0; row && depth < 8; depth += 1, row = row.parentElement) {
                            const r = row.getBoundingClientRect();
                            if (visible(row) && r.width >= 80 && r.width <= 420 && r.height >= 20 && r.height <= 130 && r.left > innerWidth * .25 && r.right < innerWidth * .75) break;
                        }
                        if (!row) return null;
                        const r = row.getBoundingClientRect();
                        const hasAvatar = Array.from(row.querySelectorAll('img')).some(visible);
                        return {text: String(source.innerText || source.textContent || '').trim(), rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}, hasAvatar};
                    }).filter(Boolean)
                    .filter(item => !item.hasAvatar)
                    .sort((a, b) => b.rect.y - a.rect.y);
                return nodes[0] ? {found: true, notice: nodes[0]} : {found: false};
            }''')
            if not notice.get('found'):
                return _fail('撤回本次消息后未找到无头像的系统提示消息', notice)
            return _ok('已验证本次撤回生成独立的系统提示消息', notice)
        except Exception as exc:
            return _fail(f'验证成员大厅系统提示失败: {str(exc)[:200]}')

    async def _hall_reply_banner(self, value: str) -> Dict[str, Any]:
        """Find the reply strip in the composer, never an equally named chat bubble."""
        return await self.page.evaluate(r'''value => {
            const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&r.bottom>0&&r.top<innerHeight;};
            const norm=el=>String(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
            const candidates=[];
            for(const leaf of Array.from(document.querySelectorAll('div,span,p')).filter(visible)) {
                const text=norm(leaf), r=leaf.getBoundingClientRect();
                if(r.top<innerHeight-210 || !text.includes(value) || !(/\u6b63\u5728\u56de\u590d|\u56de\u590d\s*[:：]/.test(text))) continue;
                let banner=leaf;
                for(let depth=0;banner&&depth<8;depth+=1,banner=banner.parentElement) {
                    const br=banner.getBoundingClientRect();
                    if(visible(banner)&&br.top>=innerHeight-210&&br.width>=300&&br.height>=30&&br.height<=110) {
                        candidates.push({el:banner,r:br,text:norm(banner)});
                    }
                }
            }
            const best=candidates.sort((a,b)=>a.r.height-b.r.height||b.r.width-a.r.width)[0];
            if(!best)return {found:false};
            const token='ai-hall-reply-banner-'+Date.now(); best.el.setAttribute('data-ai-hall-reply-banner',token);
            return {found:true,selector:'[data-ai-hall-reply-banner="'+token+'"]',rect:{x:Math.round(best.r.x),y:Math.round(best.r.y),w:Math.round(best.r.width),h:Math.round(best.r.height)},text:best.text.slice(0,400)};
        }''', value)

    async def reply_hall_runtime_message(self, step) -> ActionResult:
        context=await self._hall_context(); value=context.get('original') or context.get('last','')
        if not value:
            value=f'HALL_{int(time.time() * 1000)}_回复上下文'
            created=await self.send_hall_message({'input_value':value,'message_role':'original'})
            if created.get('status')!='completed': return created
        menu=await self._open_hall_message_menu(value)
        if menu.get('status')!='completed': return menu
        operation=await self._click_hall_menu_operation('回复')
        if operation.get('status')!='completed': return operation
        banner=await self._hall_reply_banner(value)
        return _ok('成员大厅输入区已进入回复状态', {'value':value,'banner':banner}) if banner.get('found') else _fail('点击回复后输入区未出现本次消息的回复上下文', {'value':value,'banner':banner})

    async def cancel_hall_reply(self, step) -> ActionResult:
        context=await self._hall_context(); value=context.get('original') or context.get('last','')
        try:
            scan=await self._hall_reply_banner(value)
            if not scan.get('found'): return _fail('未找到成员大厅回复状态的取消入口', {'value':value})
            rect=scan['rect']
            # The close glyph is fixed at the right edge of the reply strip.
            # Clicking the strip's own coordinate avoids unrelated reply text
            # and controls in the virtualized message list.
            await self.page.mouse.click(rect['x'] + rect['w'] - 32, rect['y'] + rect['h'] / 2)
            dismissed=False
            for _ in range(10):
                await asyncio.sleep(0.25)
                if not (await self._hall_reply_banner(value)).get('found'):
                    dismissed=True
                    break
            if not dismissed:
                return _fail('点击取消后成员大厅仍保留本次回复状态', {'value':value,'banner':await self._hall_reply_banner(value)})
            cleanup=await self.retract_hall_runtime_message({'message_role':'original'})
            if cleanup.get('status')!='completed': return _fail('已取消回复状态，但清理本次原始消息失败', {'cleanup':cleanup.get('element')})
            return _ok('已取消成员大厅回复状态并清理本次原始消息')
        except Exception as exc: return _fail(f'取消成员大厅回复状态失败: {str(exc)[:200]}')

    async def top_community_search(self, step) -> ActionResult:
        keyword = str(step.get('input_value') or step.get('target_text') or '').strip()
        open_only = bool(step.get('open_only'))
        if not keyword and not open_only:
            return _fail('顶部社区搜索缺少搜索关键词')

        async def find_popup_input():
            result = await self.page.evaluate(r"""() => {
                const visible = (el) => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
                };
                const inputs = Array.from(document.querySelectorAll('input')).filter(visible).map((el) => {
                    const ph = el.getAttribute('placeholder') || '';
                    const cls = String(el.className || '');
                    const root = el.closest('[role="dialog"],.modal,.dialog,[class*="search" i],[class*="popup" i],[class*="popover" i],.ui-dialog');
                    const rootCls = String(root?.className || '');
                    const r = el.getBoundingClientRect();
                    const text = ph + ' ' + cls + ' ' + rootCls;
                    let score = 0;
                    if (/搜索社区/.test(ph)) score += 2200;
                    if (/用户昵称|NN号/.test(ph)) score += 1400;
                    if (/搜索/.test(ph)) score += 600;
                    if (/全部社区/.test(ph)) score -= 3000;
                    if (/ui-dialog|dialog|modal|popup|popover/i.test(rootCls)) score += 500;
                    if (r.top < 260) score += 200;
                    return {el, ph, score, cls: cls.slice(0,120), rootCls: rootCls.slice(0,120), rect:{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)}};
                }).sort((a,b)=>b.score-a.score);
                const best = inputs.find(x => x.score > 0);
                if (!best) return {found:false, samples:inputs.slice(0,8).map(x=>({ph:x.ph,score:x.score,cls:x.cls,rootCls:x.rootCls,rect:x.rect}))};
                const token = 'ai_top_search_input_' + Date.now() + '_' + Math.random().toString(36).slice(2);
                best.el.setAttribute('data-ai-automation-input-target', token);
                return {found:true, selector:'[data-ai-automation-input-target="' + token + '"]', detail:{ph:best.ph,score:best.score,cls:best.cls,rootCls:best.rootCls,rect:best.rect}, samples:inputs.slice(0,8).map(x=>({ph:x.ph,score:x.score,cls:x.cls,rootCls:x.rootCls,rect:x.rect}))};
            }""")
            if result and result.get('found'):
                return result['selector'], self.page.locator(result['selector']).first
            return None, None

        input_selector, input_loc = await find_popup_input()
        trigger_logs = []
        if not input_loc:
            candidates = await self.page.evaluate(r"""() => {
                const visible = (el) => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
                };
                const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
                const nodes = Array.from(document.querySelectorAll('header *,.appHeader *,[class*="header" i] *,[class*="nav" i] *')).filter(visible);
                const out=[];
                for (const el of nodes) {
                    const text = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '');
                    const cls = String(el.className || '');
                    const combined = text + ' ' + cls;
                    if (!/(搜索|search|sousuo|nicon-a-search)/i.test(combined)) continue;
                    let clickEl = el.closest('button,a,[role="button"],[class*="cursor-pointer" i],[class*="search" i]') || el;
                    if (!visible(clickEl)) continue;
                    const r = clickEl.getBoundingClientRect();
                    let score = 0;
                    if (r.top < 140) score += 500;
                    if (/nicon-a-search-linesousuo-xianxing/.test(cls)) score += 1600;
                    if (/cursor-pointer|search|sousuo/i.test(String(clickEl.className || '') + ' ' + cls)) score += 500;
                    if (/EPIC平台/.test(text)) score -= 1200;
                    if (/搜索/.test(text)) score += 200;
                    const token = 'ai_top_search_trigger_' + out.length + '_' + Date.now();
                    clickEl.setAttribute('data-ai-automation-search-trigger', token);
                    out.push({selector:'[data-ai-automation-search-trigger="' + token + '"]', score, text, cls:String(clickEl.className||'').slice(0,120), rect:{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)}});
                }
                return out.sort((a,b)=>b.score-a.score).slice(0,8);
            }""")
            for cand in candidates or []:
                try:
                    await self.page.locator(cand['selector']).first.click(timeout=2500, force=True)
                except Exception:
                    try:
                        await self.page.evaluate('(s) => { const e = document.querySelector(s); if (e) e.click(); }', cand['selector'])
                    except Exception:
                        pass
                await asyncio.sleep(0.8)
                trigger_logs.append(cand)
                input_selector, input_loc = await find_popup_input()
                if input_loc:
                    break
        _log(self.execution_record, f'BUSINESS_ACTION nn_top_community_search triggers={trigger_logs[:3]}')
        if not input_loc:
            return _fail('未找到顶部搜索弹层输入框，已拒绝使用页面中部搜索框')
        if open_only:
            try:
                await input_loc.focus(timeout=1500)
                is_focused = await input_loc.evaluate('(el) => document.activeElement === el')
            except Exception as exc:
                return _fail('顶部社区搜索框已出现，但无法获取输入焦点', {'selector': input_selector, 'error': str(exc)[:200]})
            if not is_focused:
                return _fail('顶部社区搜索框已出现，但输入框未获得焦点', {'selector': input_selector})
            _log(self.execution_record, f'BUSINESS_ACTION nn_open_top_search input={input_selector}')
            return _ok('已打开顶部社区搜索框并确认输入框可输入', {'selector': input_selector})
        if not await _fill_and_verify(input_loc, keyword):
            return _fail('顶部搜索关键词输入后读取值不一致', {'selector': input_selector})
        await self.page.keyboard.press('Enter')
        await asyncio.sleep(2)
        _log(self.execution_record, f'BUSINESS_ACTION nn_top_community_search input={input_selector} keyword={keyword}')
        return _ok('已完成顶部社区搜索', {'selector': input_selector, 'keyword': keyword})

    async def open_recruitment(self, step) -> ActionResult:
        """Open the recruitment dialog and prove that the expected dialog rendered.

        A text-only generic click can accidentally hit a non-interactive label or
        a stale duplicate. Recruitment follows with form operations, so this
        entry point must converge on the actual dialog before continuing.
        """
        scan_script = r'''() => {
            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect(), s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
            };
            const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
            const dialogs = Array.from(document.querySelectorAll('[role="dialog"],.ui-dialog,.nn-dialog,.nn-modal,.modal,.dialog,[class*="dialog" i],[class*="modal" i],[class*="drawer" i],[class*="popup" i]'))
                .filter(visible)
                .map(root => ({root, text: norm(root.innerText || root.textContent)}))
                .filter(item => /\u9009\u62e9\u533a\u670d/.test(item.text) && /\u62db\u52df\u961f\u53cb\u4fe1\u606f|\u53d1\u5e03\u62db\u52df\u4fe1\u606f|\u53d1\u5e03\u62db\u52df/.test(item.text));
            if (dialogs.length) {
                const dialog = dialogs.sort((a, b) => (b.root.getBoundingClientRect().width * b.root.getBoundingClientRect().height) - (a.root.getBoundingClientRect().width * a.root.getBoundingClientRect().height))[0];
                return {opened: true, dialogText: dialog.text.slice(0, 500)};
            }
            const candidatesByClickable = new Map();
            for (const el of Array.from(document.querySelectorAll('button,a,[role="button"],div,span'))) {
                if (!visible(el) || norm(el.innerText || el.textContent) !== '\u62db\u52df\u961f\u53cb') continue;
                const clickable = el.closest('button,a,[role="button"],[tabindex],[class*="button" i],[class*="btn" i],[class*="click" i]') || el;
                if (!visible(clickable)) continue;
                const rect = clickable.getBoundingClientRect();
                const text = norm(clickable.innerText || clickable.textContent);
                if (rect.width < 12 || rect.height < 12) continue;
                let score = 0;
                if (clickable.matches('button,a,[role="button"]')) score += 100;
                if (/button|btn|click/i.test(String(clickable.className || ''))) score += 50;
                if (text === '\u62db\u52df\u961f\u53cb') score += 40;
                const current = candidatesByClickable.get(clickable);
                if (!current || score > current.score) {
                    candidatesByClickable.set(clickable, {clickable, text, score, rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)}});
                }
            }
            const candidates = Array.from(candidatesByClickable.values())
                .sort((a, b) => b.score - a.score)
                .slice(0, 8)
                .map((candidate, index) => {
                    const token = 'ai-recruitment-entry-' + index + '-' + Date.now() + '-' + Math.random().toString(36).slice(2);
                    candidate.clickable.setAttribute('data-ai-recruitment-entry', token);
                    return {selector: `[data-ai-recruitment-entry="${token}"]`, text: candidate.text, score: candidate.score, rect: candidate.rect};
                });
            return {opened: false, candidates};
        }'''

        scan = await self.page.evaluate(scan_script)
        _log(self.execution_record, f'BUSINESS_ACTION nn_open_recruitment initial_scan={scan}')
        if scan and scan.get('opened'):
            return _ok('招募信息弹窗已处于打开状态', {'scan': scan})

        candidates = (scan or {}).get('candidates') or []
        if not candidates:
            return _fail('未找到可点击的「招募队友」入口', {'scan': scan})

        attempts = []
        for candidate in candidates[:3]:
            try:
                locator = self.page.locator(candidate['selector']).first
                await locator.scroll_into_view_if_needed(timeout=3000)
                await locator.click(timeout=3000, force=True)
            except Exception as exc:
                attempts.append({**candidate, 'error': str(exc)[:180]})
                continue
            await asyncio.sleep(0.7)
            scan = await self.page.evaluate(scan_script)
            attempts.append({**candidate, 'opened': bool(scan and scan.get('opened'))})
            if scan and scan.get('opened'):
                _log(self.execution_record, f'BUSINESS_ACTION nn_open_recruitment opened attempts={attempts}')
                return _ok('已打开招募信息弹窗并确认页面状态', {'scan': scan, 'attempts': attempts})

        _log(self.execution_record, f'BUSINESS_ACTION nn_open_recruitment failed attempts={attempts} scan={scan}')
        return _fail('点击「招募队友」后未出现招募信息弹窗', {'attempts': attempts, 'scan': scan})

    async def submit_recruitment(self, step) -> ActionResult:
        """Submit only the active recruitment dialog and prove the click had an effect."""
        scan = await self.page.evaluate(r'''() => {
            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect(), s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
            };
            const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
            const roots = Array.from(document.querySelectorAll('[role="dialog"],.ui-dialog,.nn-dialog,.nn-modal,.modal,.dialog,[class*="dialog" i],[class*="modal" i]'))
                .filter(visible)
                .filter(root => /\u9009\u62e9\u533a\u670d/.test(norm(root.innerText || root.textContent)) && /\u62db\u52df\u961f\u53cb\u4fe1\u606f/.test(norm(root.innerText || root.textContent)));
            const root = roots.sort((a, b) => (b.getBoundingClientRect().width * b.getBoundingClientRect().height) - (a.getBoundingClientRect().width * a.getBoundingClientRect().height))[0];
            if (!root) return {found: false, reason: '\u672a\u627e\u5230\u53d1\u5e03\u62db\u52df\u4fe1\u606f\u5f39\u7a97'};
            const button = Array.from(root.querySelectorAll('button,[role="button"]')).filter(visible).find(el => norm(el.innerText || el.textContent) === '\u786e\u5b9a\u53d1\u5e03');
            if (!button) return {found: false, reason: '\u62db\u52df\u5f39\u7a97\u5185\u672a\u627e\u5230\u786e\u5b9a\u53d1\u5e03\u6309\u94ae'};
            const rootToken = 'ai-recruitment-dialog-' + Date.now();
            const buttonToken = 'ai-recruitment-submit-' + Date.now();
            root.setAttribute('data-ai-recruitment-dialog', rootToken);
            button.setAttribute('data-ai-recruitment-submit', buttonToken);
            return {
                found: true,
                dialog: `[data-ai-recruitment-dialog="${rootToken}"]`,
                button: `[data-ai-recruitment-submit="${buttonToken}"]`,
                text: norm(root.innerText || root.textContent).slice(0, 500),
            };
        }''')
        _log(self.execution_record, f'BUSINESS_ACTION nn_submit_recruitment scan={scan}')
        if not scan or not scan.get('found'):
            return _fail((scan or {}).get('reason') or '未定位到招募发布弹窗')
        try:
            await self.page.locator(scan['button']).first.click(timeout=5000)
        except Exception as exc:
            return _fail('确定发布按钮点击失败: ' + str(exc)[:200], {'scan': scan})
        # The target UI renders its submit feedback asynchronously after the
        # click. Give that state a chance to enter the composed DOM.
        await asyncio.sleep(1.2)
        outcome = await self.page.evaluate(r'''(payload) => {
            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect(), s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
            };
            const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
            const root = document.querySelector(payload.dialog);
            const dialogVisible = visible(root);
            const hasError = node => {
                if (!node) return false;
                const meta = `${norm(node.innerText || node.textContent)} ${node.className || ''}`;
                return /\u5fc5\u586b|\u4e0d\u80fd\u4e3a\u7a7a|\u8bf7\u9009\u62e9|\u8bf7\u586b\u5199|\u6821\u9a8c|\u9519\u8bef/.test(meta) || /error|invalid|danger|validate/i.test(meta) || !!node.querySelector('[aria-invalid="true"],.is-error,[class*="error" i],[class*="invalid" i]');
            };
            const labels = ['\u9009\u62e9\u533a\u670d', '\u62db\u52df\u961f\u53cb\u4fe1\u606f'];
            const fields = labels.map(label => {
                const node = Array.from(root?.querySelectorAll('label,span,p,div') || []).find(el => norm(el.innerText || el.textContent) === label);
                let fieldError = false;
                for (let current = node; current && current !== root; current = current.parentElement) {
                    if (hasError(current)) { fieldError = true; break; }
                }
                return {label, fieldError};
            });
            const hasValidation = fields.some(field => field.fieldError);
            const allElements = root => {
                const nodes = [];
                const visit = current => {
                    for (const el of current.querySelectorAll('*')) {
                        nodes.push(el);
                        if (el.shadowRoot) visit(el.shadowRoot);
                    }
                };
                visit(root);
                return nodes;
            };
            const feedbackNodes = allElements(document).filter(el => el.matches?.('[role="alert"],.toast,.message,.notification,[class*="toast" i],[class*="message" i],[class*="notice" i]')).filter(visible);
            const transientNodes = allElements(document).filter(el => {
                if (!visible(el)) return false;
                const text = norm(el.innerText || el.textContent);
                if (text.length < 2 || text.length > 80) return false;
                if (Array.from(el.children).some(child => norm(child.innerText || child.textContent) === text)) return false;
                const rect = el.getBoundingClientRect();
                let positioned = false;
                for (let parent = el, depth = 0; parent && depth < 5; parent = parent.parentElement, depth += 1) {
                    if (['fixed', 'absolute', 'sticky'].includes(getComputedStyle(parent).position)) { positioned = true; break; }
                }
                return positioned && rect.top < innerHeight * 0.5;
            });
            const feedback = [...new Set([...feedbackNodes, ...transientNodes].map(el => norm(el.innerText || el.textContent)).filter(Boolean))];
            const success = feedback.some(text => /\u53d1\u5e03\u6210\u529f|\u53d1\u5e03\u5b8c\u6210/.test(text));
            const relevantFeedback = feedback.filter(text => /\u53d1\u5e03\u6210\u529f|\u53d1\u5e03\u5b8c\u6210|\u5fc5\u586b|\u4e0d\u80fd\u4e3a\u7a7a|\u8bf7.*(?:\u5b8c\u5584|\u9009\u62e9|\u586b\u5199|\u8f93\u5165)|\u6821\u9a8c|\u9519\u8bef/.test(text));
            const hasValidationFeedback = relevantFeedback.some(text => /\u5fc5\u586b|\u4e0d\u80fd\u4e3a\u7a7a|\u8bf7.*(?:\u5b8c\u5584|\u9009\u62e9|\u586b\u5199|\u8f93\u5165)|\u6821\u9a8c|\u9519\u8bef/.test(text));
            return {dialogVisible, hasValidation: hasValidation || hasValidationFeedback, fields, feedback: relevantFeedback, success, dialogText: norm(root?.innerText || root?.textContent).slice(0, 500)};
        }''', {'dialog': scan['dialog']})
        _log(self.execution_record, f'BUSINESS_ACTION nn_submit_recruitment outcome={outcome}')
        if outcome.get('hasValidation') or outcome.get('success'):
            return _ok('确定发布已在招募弹窗内触发并检测到反馈', {'scan': scan, 'outcome': outcome})
        if outcome.get('dialogVisible'):
            return _ok('确定发布已触发，表单仍保持打开并等待必填项完成', {
                'scan': scan,
                'outcome': {**outcome, 'submissionBlocked': True},
            })
        return _fail('确定发布点击后未出现校验提示或发布成功反馈', {'scan': scan, 'outcome': outcome})

    async def click_community_result(self, step) -> ActionResult:
        target = str(step.get('target_text') or step.get('input_value') or '').strip()
        required_signals = [
            str(item).strip()
            for item in (step.get('required_signals') or [])
            if str(item).strip()
        ]
        if not required_signals and step.get('display_description'):
            required_signals = extract_click_constraints(
                str(step.get('display_description') or ''),
                fallback_target=target,
            ).get('required_signals', [])
        if not target:
            return _fail('社区结果点击缺少目标文本')
        if required_signals:
            result = await self.page.evaluate(r"""(payload) => {
                const targets = Array.isArray(payload?.targets) ? payload.targets : [];
                const requiredSignals = Array.isArray(payload?.requiredSignals) ? payload.requiredSignals : [];
                const allowTeamResult = targets.some(target => /\u6218\u961f|\u56e2\u961f|team/i.test(target));
                const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
                const hasOnlineCount = (text) => /在线\s*\d+|\d+\s*在线|在线人数|人在线|在线成员|成员\s*\d+/.test(text);
                const hasCommunityIntro = (text, matchedTarget) => {
                    const normalized = norm(text);
                    const stripped = norm(
                        normalized
                            .replaceAll(matchedTarget || '', '')
                            .replaceAll('社区', '')
                            .replace(/\d+\s*(在线|成员)?/g, '')
                    );
                    return stripped.length >= 16 || /简介|介绍|官方社区|射击|攻略|战队|活动|赛事|交流/.test(normalized);
                };
                const visible = (el) => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const st = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
                };
                const dialog = Array.from(document.querySelectorAll('[role="dialog"], .ui-dialog, .nn-dialog, .nn-modal, .modal, .dialog, [class*="dialog" i], [class*="modal" i]'))
                    .filter(visible)
                    .sort((a, b) => (b.getBoundingClientRect().width * b.getBoundingClientRect().height) - (a.getBoundingClientRect().width * a.getBoundingClientRect().height))[0] || document.body;
                const rawNodes = Array.from(dialog.querySelectorAll('a,[role="link"],[role="button"],button,li,[class*="card" i],[class*="item" i],[class*="result" i],[class*="community" i],[class*="group" i],div'));
                const candidateMap = new Map();
                for (const el of rawNodes) {
                    if (!visible(el)) continue;
                    const leafText = norm(el.innerText || el.textContent || '');
                    const matchedTarget = targets.find(t => leafText.includes(t));
                    if (!matchedTarget) continue;
                    let clickEl = el.closest('a,[role="link"],[role="button"],button,li,[class*="card" i],[class*="item" i],[class*="result" i],[class*="community" i],[class*="group" i],[class*="cursor-pointer" i]') || el;
                    if (!visible(clickEl)) continue;
                    // Some search-result cards bind Vue's click handler on a
                    // neutral flex wrapper. Prefer the smallest enclosing
                    // card-shaped ancestor that owns the result image, rather
                    // than a text-only child that merely closes the overlay.
                    for (let parent = clickEl.parentElement, depth = 0; parent && depth < 5 && dialog.contains(parent); parent = parent.parentElement, depth += 1) {
                        if (!visible(parent)) continue;
                        const pr = parent.getBoundingClientRect();
                        const parentText = norm(parent.innerText || parent.textContent || '');
                        if (pr.width < clickEl.getBoundingClientRect().width || pr.height < clickEl.getBoundingClientRect().height || pr.width > dialog.getBoundingClientRect().width * .92 || pr.height > 240) continue;
                        if (parentText.includes(matchedTarget) && hasOnlineCount(parentText) && parent.querySelector('img,[role="img"]')) {
                            clickEl = parent;
                            break;
                        }
                    }
                    const clickText = norm(clickEl.innerText || clickEl.textContent || leafText);
                    if (!clickText || clickText.length > 800) continue;
                    const cls = String(clickEl.className || '');
                    const r = clickEl.getBoundingClientRect();
                    const drRect = dialog.getBoundingClientRect();
                    const isRightSideResult = r.left > drRect.left + drRect.width / 2 + 50;
                    const isCommunityCard = /(community|card|result|item|社区|加入|已加入|成员|帖子|精华)/i.test(cls + ' ' + clickText);
                    const isUserEntity = /(avatar|user|profile|头像|用户|个人主页|粉丝|关注|NN[:：]\s*\d+|等级|Lv\.|Lv\d)/i.test(cls + ' ' + clickText);
                    const hasOfficialCommunityLabel = /官方社区|PUBG中国官方社区|社区主页/i.test(clickText);
                    const isTeamLike = /\u6218\u961f|\u56e2\u961f|team/i.test(cls + ' ' + clickText);
                    if (isTeamLike && !allowTeamResult) continue;
                    const requirementFlags = {
                        online_count: hasOnlineCount(clickText),
                        community_intro: hasCommunityIntro(clickText, matchedTarget),
                    };
                    const requirementsMetAll = requiredSignals.every(signal => requirementFlags[signal]);
                    let score = 0;
                    if (isRightSideResult && (isCommunityCard || hasOfficialCommunityLabel)) score += 5000;
                    if (isRightSideResult) score += 200;
                    if (hasOfficialCommunityLabel) score += 2500;
                    if (isCommunityCard) score += 1200;
                    if (requirementFlags.online_count) score += 1800;
                    if (requirementFlags.community_intro) score += 1600;
                    if (requirementsMetAll) score += 4000;
                    if (!requirementsMetAll) score -= 5000;
                    if (/社区|community/i.test(clickText + ' ' + cls)) score += 600;
                    if (/card|community|result|item/i.test(cls)) score += 300;
                    if (/cursor-pointer/.test(cls)) score += 100;
                    if (clickText === matchedTarget || clickText.startsWith(matchedTarget + ' ')) score += 80;
                    if (clickEl !== el) score += 120;
                    if (r.width > 180 && r.height > 40 && r.height < 220) score += 150;
                    if (isUserEntity) score -= 10000;
                    if (r.height > 250 || r.width > 600) score -= 800;
                    if (/simplebar|scroller|wrapper|mask|flex-1 h-0/i.test(cls)) score -= 900;
                    score -= Math.max(0, Math.abs(r.top - drRect.top) - 60);
                    const candidate = {
                        el: clickEl,
                        score,
                        text: clickText.slice(0, 220),
                        cls: cls.slice(0, 160),
                        rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)},
                        isUserEntity,
                        isRightSideResult,
                        isCommunityCard,
                        hasOfficialCommunityLabel,
                        matchedTarget,
                        requirementFlags,
                        requirementsMetAll,
                    };
                    const existing = candidateMap.get(clickEl);
                    if (!existing || candidate.score > existing.score) {
                        candidateMap.set(clickEl, candidate);
                    }
                }
                const candidates = Array.from(candidateMap.values()).sort((a, b) => b.score - a.score);
                const validCandidates = candidates.filter(c =>
                    !c.isUserEntity &&
                    c.score > 0 &&
                    (c.isRightSideResult || c.isCommunityCard || c.hasOfficialCommunityLabel || c.requirementsMetAll)
                );
                const strictCandidates = validCandidates.filter(c => c.requirementsMetAll);
                if (strictCandidates.length === 0) {
                    return {
                        found: false,
                        reason: 'no_candidate_matching_required_signals',
                        requiredSignals,
                        debug: {total: candidates.length, valid: validCandidates.length},
                        samples: candidates.slice(0, 8).map(c => ({
                            score: c.score,
                            text: c.text,
                            cls: c.cls,
                            rect: c.rect,
                            requirementFlags: c.requirementFlags,
                            requirementsMetAll: c.requirementsMetAll,
                        })),
                    };
                }
                const best = strictCandidates[0];
                const token = 'ai_community_result_' + Date.now() + '_' + Math.random().toString(36).slice(2);
                best.el.setAttribute('data-ai-automation-click-target', token);
                return {
                    found: true,
                    selector: '[data-ai-automation-click-target="' + token + '"]',
                    detail: {
                        score: best.score,
                        text: best.text,
                        cls: best.cls,
                        rect: best.rect,
                        matchedTarget: best.matchedTarget,
                        requirementFlags: best.requirementFlags,
                        requirementsMetAll: best.requirementsMetAll,
                        requiredSignals,
                    },
                };
            }""", {'targets': [target, target + '绀惧尯'], 'requiredSignals': required_signals})
            _log(self.execution_record, f'BUSINESS_ACTION nn_click_community_result scan={result}')
            if not result or not result.get('found'):
                return _fail('鏈壘鍒扮鍚堢ぞ鍖哄疄浣撶害鏉熺殑鎼滅储缁撴灉', {'scan': result})
            loc = self.page.locator(result['selector']).first
            await loc.click(timeout=5000, force=True)
            await asyncio.sleep(2)
            detail = result.get('detail') or {}
            detail['community_identity'] = _community_identity_from_card_detail(detail)
            return _ok('宸茬偣鍑荤ぞ鍖烘悳绱㈢粨鏋?', {'selector': result['selector'], 'detail': detail})
        result = await self.page.evaluate(r"""(targets) => {
            const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
            const visible = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
            };
            const dialog = Array.from(document.querySelectorAll('[role="dialog"], .ui-dialog, .nn-dialog, .nn-modal, .modal, .dialog, [class*="dialog" i], [class*="modal" i]'))
                .filter(visible)
                .sort((a, b) => (b.getBoundingClientRect().width * b.getBoundingClientRect().height) - (a.getBoundingClientRect().width * a.getBoundingClientRect().height))[0] || document.body;
            const dr = dialog.getBoundingClientRect();
            const rawNodes = Array.from(dialog.querySelectorAll('a,[role="link"],[role="button"],button,li,[class*="card" i],[class*="item" i],[class*="result" i],[class*="community" i],[class*="group" i],div'));
            const candidates = [];
            for (const el of rawNodes) {
                if (!visible(el)) continue;
                const text = norm(el.innerText || el.textContent || '');
                if (!text || text.length > 600) continue;
                const matchedTarget = targets.find(t => text.includes(t));
                if (!matchedTarget) continue;
                const cls = String(el.className || '');
                const r = el.getBoundingClientRect();
                const drRect = dialog.getBoundingClientRect();
                // 严格的右侧区域判定：必须在页面右半部分（搜索结果弹窗通常在右侧）
                const isRightSideResult = r.left > drRect.left + drRect.width / 2 + 50;
                // 社区卡片特征判定
                const isCommunityCard = /(community|card|result|item|社区|加入|已加入|成员|帖子|精华)/i.test(cls + ' ' + text);
                // 用户特征判定（严厉惩罚，这些绝对不能点）
                const isUserEntity = /(avatar|user|profile|头像|用户|个人主页|粉丝|关注|NN[:：]\s*\d+|等级|Lv\.|Lv\d)/i.test(cls + ' ' + text);
                const hasOfficialCommunityLabel = /官方社区|PUBG中国官方社区|社区主页/i.test(text);
                
                let clickEl = el.closest('a,[role="link"],[role="button"],button,li,[class*="card" i],[class*="item" i],[class*="result" i],[class*="community" i],[class*="group" i],[class*="cursor-pointer" i]') || el;
                if (!visible(clickEl)) continue;
                
                let score = 0;
                // === 核心约束：右侧 + 社区标签 = 极高权重 ===
                if (isRightSideResult && (isCommunityCard || hasOfficialCommunityLabel)) score += 5000;
                // 右侧区域单独加分（搜索结果通常在右侧）
                if (isRightSideResult) score += 2000;
                // 社区相关信号
                if (hasOfficialCommunityLabel) score += 2500;
                if (isCommunityCard) score += 1200;
                // 普通社区信号
                if (/社区|community/i.test(text + ' ' + cls)) score += 600;
                // 卡片/结果样式
                if (/card|community|result|item/i.test(cls)) score += 300;
                if (/cursor-pointer/.test(cls)) score += 100;
                if (text === matchedTarget || text.startsWith(matchedTarget + ' ')) score += 80;
                if (clickEl !== el) score += 120;
                // 合理的社区卡片尺寸
                if (r.width > 180 && r.height > 40 && r.height < 200) score += 150;
                // === 绝对禁止：用户相关 ===
                if (isUserEntity) score -= 10000;
                // 异常大的元素（通常是容器而非可点击项）
                if (r.height > 250 || r.width > 600) score -= 800;
                if (/simplebar|scroller|wrapper|mask|flex-1 h-0/i.test(cls)) score -= 900;
                // 位置：不要太靠上或太靠下
                score -= Math.max(0, Math.abs(r.top - drRect.top) - 60);
                
                candidates.push({el: clickEl, score, text: text.slice(0, 160), cls: cls.slice(0, 160), rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}, isUserEntity, isRightSideResult, isCommunityCard, hasOfficialCommunityLabel, matchedTarget});
            }
            candidates.sort((a, b) => b.score - a.score);
            // 严格过滤：必须满足 右侧 OR 社区信号 OR 社区标签
            const validCandidates = candidates.filter(c => !c.isUserEntity && c.score > 0 && (c.isRightSideResult || c.isCommunityCard || c.hasOfficialCommunityLabel));
            const best = validCandidates[0];
            if (!best) {
                return {found: false, reason: best ? 'no_valid_community_entity' : 'no_candidate', debug: {total: candidates.length, valid: validCandidates.length}, samples: candidates.slice(0, 8).map(c => ({score:c.score,text:c.text,cls:c.cls,rect:c.rect,isUserEntity:c.isUserEntity,isRightSideResult:c.isRightSideResult,isCommunityCard:c.isCommunityCard,hasOfficialCommunityLabel:c.hasOfficialCommunityLabel,matchedTarget:c.matchedTarget}))};
            }
            const token = 'ai_community_result_' + Date.now() + '_' + Math.random().toString(36).slice(2);
            best.el.setAttribute('data-ai-automation-click-target', token);
            return {found: true, selector: '[data-ai-automation-click-target="' + token + '"]', detail: {score: best.score, text: best.text, cls: best.cls, rect: best.rect, isUserLike: best.isUserLike, hasCommunitySignal: best.hasCommunitySignal, isRightSide: best.isRightSide, matchedTarget: best.matchedTarget}, samples: candidates.slice(0, 5).map(c => ({score:c.score,text:c.text,cls:c.cls,rect:c.rect,isUserLike:c.isUserLike,hasCommunitySignal:c.hasCommunitySignal,isRightSide:c.isRightSide,matchedTarget:c.matchedTarget}))};
        }""", [target, target + '社区'])
        _log(self.execution_record, f'BUSINESS_ACTION nn_click_community_result scan={result}')
        if not result or not result.get('found'):
            return _fail('未找到符合社区实体约束的搜索结果', {'scan': result})
        loc = self.page.locator(result['selector']).first
        await loc.click(timeout=5000, force=True)
        await asyncio.sleep(2)
        detail = result.get('detail') or {}
        detail['community_identity'] = _community_identity_from_card_detail(detail)
        return _ok('已点击社区搜索结果', {'selector': result['selector'], 'detail': detail})


    async def query_battle_records(self, step) -> ActionResult:
        """Query a player and wait until the result dialog is genuinely open."""
        player = str(step.get('player_name') or step.get('input_value') or '').strip()
        if not player:
            return _fail('查询战绩需要提供玩家名称')
        try:
            scan = await self.page.evaluate(r'''() => {
                const visible = el => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < innerHeight
                        && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
                };
                    const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
                    const candidates = Array.from(document.querySelectorAll('input,textarea')).filter(visible).map(el => {
                    const meta = norm([
                        el.placeholder || '', el.name || '', el.id || '',
                        el.getAttribute('aria-label') || '', el.parentElement?.innerText || '',
                    ].join(' '));
                    let score = 0;
                    // This action represents the public player-search box.
                    // The adjacent game-ID authorization field is a different
                    // workflow and can impose a shorter max length.
                    if (/查询玩家战绩|玩家战绩/.test(meta)) score += 4200;
                    if (/输入游戏\s*id|游戏\s*id|game\s*id|gameid/i.test(meta)) score -= 2600;
                    if (/查询|搜索|玩家|战绩|pubg/i.test(meta)) score += 700;
                    if (/搜索社区|用户名称|nn号/i.test(meta)) score -= 2400;
                    if (el.tagName === 'INPUT') score += 100;
                    return {el, score, meta: meta.slice(0, 220)};
                }).filter(item => item.score > 0).sort((a, b) => b.score - a.score);
                const best = candidates[0];
                if (!best) return {found: false, candidates: []};
                const token = 'ai-battle-query-' + Date.now() + '-' + Math.random().toString(36).slice(2);
                best.el.setAttribute('data-ai-battle-query-input', token);
                return {
                    found: true,
                    selector: '[data-ai-battle-query-input="' + token + '"]',
                    candidates: candidates.slice(0, 5).map(item => ({score: item.score, meta: item.meta})),
                };
            }''')
        except Exception as exc:
            return _fail('定位战绩查询输入框失败: ' + str(exc)[:200])
        if not scan or not scan.get('found'):
            return _fail('未找到“查询玩家战绩”输入框', {'scan': scan or {}})

        locator = self.page.locator(scan['selector']).first
        try:
            if not await _fill_and_verify(locator, player):
                return _fail('战绩查询输入值校验失败', {'selector': scan['selector'], 'player': player})
            await locator.press('Enter', timeout=5000)
        except Exception as exc:
            return _fail('提交战绩查询失败: ' + str(exc)[:200], {'selector': scan['selector'], 'player': player})

        deadline = time.monotonic() + 15
        last_state = {}
        while time.monotonic() < deadline:
            try:
                last_state = await self.page.evaluate(r'''(player) => {
                    const visible = el => {
                        const rect = el.getBoundingClientRect();
                        const style = getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < innerHeight
                            && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
                    };
                    const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
                    const roots = Array.from(document.querySelectorAll(
                        '[role="dialog"],[aria-modal="true"],.el-dialog,[class*="modal" i],[class*="dialog" i],[class*="popup" i]'
                    )).filter(visible).filter(el => /查询结果/.test(norm(el.innerText || el.textContent)));
                    const topRoots = roots.filter(root => !roots.some(other => other !== root && other.contains(root)));
                    const playerVisible = topRoots.some(root => norm(root.innerText || root.textContent).includes(player));
                    const queryInput = Array.from(document.querySelectorAll('input,textarea')).filter(visible).find(el => String(el.value || '').trim() === player);
                    const bodyText = norm(document.body && document.body.innerText || '');
                    // An existing record panel is not evidence that this
                    // query succeeded.  The response must identify the
                    // player submitted in this action as well.
                    const bodyContainsPlayer = bodyText.includes(player);
                    const inlineResultVisible = !!queryInput && bodyContainsPlayer
                        && /比赛场次|场均伤害|击杀数|吃鸡率/.test(bodyText);
                    const errorNodes = Array.from(document.querySelectorAll(
                        '[role="alert"],[class*="toast" i],[class*="message" i],[class*="notice" i],[class*="error" i]'
                    )).filter(visible).map(el => norm(el.innerText || el.textContent)).filter(text => /请输入有效的游戏ID|搜索失败|查询失败|请求失败/.test(text));
                    return {
                        dialogCount: topRoots.length,
                        playerVisible,
                        bodyContainsPlayer,
                        inlineResultVisible,
                        errorMessage: errorNodes[0] || '',
                        samples: topRoots.slice(0, 3).map(root => norm(root.innerText || root.textContent).slice(0, 220)),
                    };
                }''', player)
            except Exception as exc:
                return _fail('检查战绩查询结果失败: ' + str(exc)[:180])
            if last_state.get('errorMessage'):
                # A rejected query is an expected state for invalid input,
                # missing players, permission tests, and offline scenarios.
                # Preserve the observable outcome for the following assertion
                # instead of failing the action before that assertion runs.
                last_state['outcome'] = 'rejected'
                _log(self.execution_record, f'BUSINESS_ACTION nn_query_battle_records rejected={last_state}')
                return _ok(f'玩家查询已提交并收到页面反馈: {last_state["errorMessage"]}', {'selector': scan['selector'], 'detail': last_state})
            if (last_state.get('dialogCount') == 1 and last_state.get('playerVisible')) or last_state.get('inlineResultVisible'):
                _log(self.execution_record, f'BUSINESS_ACTION nn_query_battle_records evidence={last_state}')
                return _ok(f'已查询玩家 {player} 并加载战绩结果', {'selector': scan['selector'], 'detail': last_state})
            await asyncio.sleep(0.35)
        # The request was submitted successfully, but the page did not expose
        # a result within the action timeout.  Do not conflate this with an
        # interaction failure: later assertions decide whether a login prompt,
        # empty state, timeout message, or result panel is the expected state.
        last_state['outcome'] = 'unresolved'
        _log(self.execution_record, f'BUSINESS_ACTION nn_query_battle_records unresolved={last_state}')
        return _ok(f'已提交玩家 {player} 查询，等待后续断言确认页面结果', {'selector': scan['selector'], 'detail': last_state})

    async def click_identity_card(self, step) -> ActionResult:
        """Click one rendered card only when all stated identity fields agree."""
        target = str(step.get('target_text') or '').strip()
        expected_id = str(step.get('expected_id') or '').strip()
        require_online = bool(step.get('require_online'))
        if not target or not expected_id:
            return _fail('精确卡片点击缺少名称或 ID 约束')
        try:
            # Plugin navigation is rendered asynchronously. Do not scan the
            # previous plugin page and mistake its absence for a missing card.
            for _ in range(24):
                ready = await self.page.evaluate(r'''() => Array.from(document.querySelectorAll('[class*="discovery-game-card" i],[class*="community-card" i],[class*="team-card" i]')).some(el => { const r=el.getBoundingClientRect(), s=getComputedStyle(el); return r.width>=100&&r.height>=48&&s.display!=='none'&&s.visibility!=='hidden'; })''')
                if ready:
                    break
                await asyncio.sleep(0.25)
            scan = await self.page.evaluate(r'''(payload) => {
                const visible = el => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
                    return r.width >= 100 && r.height >= 48 && r.bottom > 0 && r.top < innerHeight
                        && r.right > 0 && r.left < innerWidth && s.display !== 'none'
                        && s.visibility !== 'hidden' && s.opacity !== '0';
                };
                const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
                const entries = new Map();
                for (const source of Array.from(document.querySelectorAll('a,button,li,div')).filter(visible)) {
                    const text = norm(source.innerText || source.textContent || '');
                    if (!text.includes(payload.target) || !text.includes(payload.expectedId)) continue;
                    const card = source.closest('a,button,li,[class*="card" i],[class*="item" i],[class*="community" i],[class*="team" i],[class*="cursor-pointer" i]') || source;
                    if (!visible(card)) continue;
                    const cardText = norm(card.innerText || card.textContent || '');
                    const cardCls = String(card.className || '');
                    const hasName = cardText.includes(payload.target);
                    const hasId = cardText.includes(payload.expectedId);
                    const hasOnline = /在线\s*\d+|\d+\s*在线/.test(cardText);
                    if (!hasName || !hasId || (payload.requireOnline && !hasOnline)) continue;
                    const rect = card.getBoundingClientRect();
                    const score = (/(?:community|team|game|discovery)[-_\s]*(?:card|item)|(?:card|item)[-_\s]*(?:community|team|game)/i.test(cardCls) ? 1000 : 0)
                        + (/(cursor-pointer|clickable)/i.test(cardCls) ? 300 : 0)
                        + Math.min(240, Math.round(rect.width * rect.height / 120));
                    const previous = entries.get(card);
                    if (!previous || score > previous.score) entries.set(card, {card, cardText, cardCls, hasOnline, rect, score});
                }
                const candidates = Array.from(entries.values()).sort((a, b) => b.score - a.score);
                const best = candidates[0];
                if (!best) {
                    return {found: false, target: payload.target, expectedId: payload.expectedId, requireOnline: payload.requireOnline, samples: candidates.slice(0, 5).map(item => ({text: item.cardText.slice(0, 180), cls: item.cardCls.slice(0, 140)}))};
                }
                const token = 'ai-identity-card-' + Date.now() + '-' + Math.random().toString(36).slice(2);
                best.card.setAttribute('data-ai-identity-card', token);
                return {found: true, selector: '[data-ai-identity-card="' + token + '"]', detail: {target: payload.target, expectedId: payload.expectedId, hasOnline: best.hasOnline, text: best.cardText.slice(0, 260), cls: best.cardCls.slice(0, 140), rect: {x: Math.round(best.rect.x), y: Math.round(best.rect.y), w: Math.round(best.rect.width), h: Math.round(best.rect.height)}}};
            }''', {'target': target, 'expectedId': expected_id, 'requireOnline': require_online})
            _log(self.execution_record, f'BUSINESS_ACTION nn_click_identity_card scan={scan}')
            if not scan or not scan.get('found'):
                return _fail('未找到同时满足名称、ID 和状态约束的卡片', {'scan': scan or {}})
            before_url = self.page.url
            await self.page.locator(scan['selector']).first.click(timeout=5000)
            for _ in range(24):
                await asyncio.sleep(0.25)
                state = await self.page.evaluate(r'''(payload) => {
                    const body = String(document.body?.innerText || '').replace(/\s+/g, ' ');
                    return {url: location.href, hasId: body.includes(payload.expectedId), hasName: body.includes(payload.target)};
                }''', {'target': target, 'expectedId': expected_id})
                if self.page.url != before_url or (state.get('hasId') and state.get('hasName')):
                    return _ok('已点击同一张满足身份约束的卡片', {'selector': scan['selector'], 'detail': scan['detail'], 'destination': state})
            return _fail('已点击身份匹配卡片，但页面未出现目标详情态', {'click': scan.get('detail'), 'url': self.page.url})
        except Exception as exc:
            return _fail(f'精确卡片点击失败: {str(exc)[:200]}')

    async def switch_chicken_rank_periods(self, step) -> ActionResult:
        periods = [str(item).strip() for item in (step.get('rank_periods') or ['日榜', '周榜', '总榜', '地区榜']) if str(item).strip()]
        if periods != ['日榜', '周榜', '总榜', '地区榜']:
            return _fail('吃鸡榜周期必须依次包含日榜、周榜、总榜、地区榜')
        try:
            result = await self.page.evaluate(r'''async (periods) => {
                const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
                const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
                const visible = el => {
                    const r=el.getBoundingClientRect(), s=getComputedStyle(el);
                    return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0';
                };
                const labelNodes = Array.from(document.querySelectorAll('div,span,button,a')).filter(visible)
                    .filter(el => norm(el.innerText || el.textContent) === '吃鸡榜');
                const label = labelNodes.sort((a,b) => a.getBoundingClientRect().width - b.getBoundingClientRect().width)[0];
                if (!label) return {passed:false, reason:'未找到可见吃鸡榜区域'};
                let root = label;
                for (let depth=0; root && depth<7; depth+=1, root=root.parentElement) {
                    const text=norm(root.innerText||root.textContent||''); const r=root.getBoundingClientRect();
                    if (r.width>=240 && r.width<=900 && r.height>=160 && r.height<=900 && /日榜.*周榜.*总榜.*地区榜/.test(text)) break;
                }
                if (!root) return {passed:false, reason:'未找到包含周期标签的吃鸡榜容器'};
                const events=[];
                for (const period of periods) {
                    const nodes=Array.from(root.querySelectorAll('button,[role="button"],a,div,span')).filter(visible);
                    const source=nodes.find(el => norm(el.innerText||el.textContent)===period);
                    if (!source) return {passed:false, reason:'吃鸡榜未找到标签 '+period, events};
                    const target=source.closest('button,[role="button"],a,[class*="cursor-pointer" i],[class*="clickable" i]') || source;
                    target.click();
                    await sleep(350);
                    const controls=Array.from(root.querySelectorAll('button,[role="button"],a,div,span')).filter(visible)
                        .filter(el => periods.includes(norm(el.innerText||el.textContent)));
                    const selected=controls.filter(el => {
                        const cls=String(el.className||''); const aria=String(el.getAttribute('aria-selected')||'');
                        return aria==='true' || /active|selected|primary|text-blue|font-\[6/.test(cls);
                    }).map(el => norm(el.innerText||el.textContent));
                    const text=norm(root.innerText||root.textContent||'');
                    const dataReady=/\b\d+\b/.test(text) && /(吃鸡|排名|榜|第\s*\d+)/.test(text);
                    events.push({period, selected, dataReady});
                    if (!selected.includes(period) || selected.filter(item => periods.includes(item)).length !== 1 || !dataReady) {
                        return {passed:false, reason:'切换 '+period+' 后未检测到唯一选中标签或排行数据', events};
                    }
                }
                return {passed:true, events};
            }''', periods)
            _log(self.execution_record, f'BUSINESS_ACTION nn_switch_chicken_rank_periods evidence={result}')
            if not result or not result.get('passed'):
                return _fail('吃鸡榜周期切换校验失败', {'result': result or {}})
            return _ok('已依次切换吃鸡榜周期并验证选中状态和排行数据', {'result': result})
        except Exception as exc:
            return _fail(f'吃鸡榜周期切换失败: {str(exc)[:200]}')

    async def rapid_filter_switch(self, step) -> ActionResult:
        """Switch a group of result filters without the generic click delay.

        The action records the exact DOM evidence needed by later assertions:
        every requested control click, URL-path stability, transient loaders,
        and whether a fullscreen overlay or large layout jump appeared.
        """
        values = [str(value).strip() for value in (step.get('filter_values') or []) if str(value).strip()]
        time_budget_seconds = max(1, int(step.get('time_budget_seconds') or 5))
        if len(values) < 2:
            return _fail('连续筛选切换至少需要两个有效筛选值')

        started = time.monotonic()
        try:
            result = await self.page.evaluate(r'''async ({values, budgetMs}) => {
                const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
                const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
                const visible = el => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < innerHeight
                        && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
                };
                const path = () => location.origin + location.pathname;
                const selector = 'button,[role="button"],[role="tab"],label,a,div,span';
                const isSelected = el => {
                    if (!el) return false;
                    const cls = String(el.className || '');
                    return !!el.checked || el.getAttribute('aria-selected') === 'true'
                        || el.getAttribute('aria-pressed') === 'true' || el.getAttribute('aria-checked') === 'true'
                        || /(^|[\s_-])(active|selected|current|checked|is-active|is-selected)([\s_-]|$)/i.test(cls);
                };
                const loadingState = () => {
                    const nodes = Array.from(document.querySelectorAll(
                        '[aria-busy="true"],[class*="loading" i],[class*="spinner" i],[class*="skeleton" i],[class*="pending" i]'
                    )).filter(visible);
                    const global = nodes.filter(el => {
                        const rect = el.getBoundingClientRect();
                        const cls = String(el.className || '');
                        const coversScreen = rect.width * rect.height >= innerWidth * innerHeight * 0.45;
                        return coversScreen || /(^|[\s_-])(fixed|mask|overlay|fullscreen)([\s_-]|$)/i.test(cls);
                    });
                    return {
                        count: nodes.length,
                        globalCount: global.length,
                        samples: nodes.slice(0, 4).map(el => ({
                            cls: String(el.className || '').slice(0, 140),
                            text: norm(el.innerText || el.textContent).slice(0, 80),
                        })),
                    };
                };
                const viewportSignature = () => {
                    const main = document.querySelector('main,[role="main"],[class*="result" i],[class*="record" i]');
                    const rect = main && main.getBoundingClientRect();
                    return {
                        scrollHeight: document.documentElement.scrollHeight,
                        mainHeight: rect ? Math.round(rect.height) : 0,
                    };
                };
                const bestTarget = target => {
                    const seen = new Set();
                    const candidates = [];
                    for (const el of document.querySelectorAll(selector)) {
                        if (!visible(el)) continue;
                        const text = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
                        if (text !== target) continue;
                        const clickEl = el.closest('button,[role="button"],[role="tab"],label,a,[class*="tab" i],[class*="filter" i],[class*="option" i]') || el;
                        if (!visible(clickEl) || seen.has(clickEl)) continue;
                        seen.add(clickEl);
                        const cls = String(clickEl.className || '');
                        let score = 0;
                        if (/^(BUTTON|A|LABEL)$/i.test(clickEl.tagName)) score += 500;
                        if (clickEl.getAttribute('role') === 'tab' || clickEl.getAttribute('role') === 'button') score += 450;
                        if (/tab|filter|option|select|match|record|query/i.test(cls)) score += 250;
                        if (isSelected(clickEl)) score += 80;
                        const rect = clickEl.getBoundingClientRect();
                        if (rect.width >= 20 && rect.width <= 360 && rect.height >= 18 && rect.height <= 100) score += 80;
                        candidates.push({el: clickEl, score, text, cls: cls.slice(0, 160)});
                    }
                    candidates.sort((a, b) => b.score - a.score);
                    return candidates[0] || null;
                };
                const groupSelected = target => {
                    const candidates = Array.from(document.querySelectorAll(selector)).filter(visible).filter(el => {
                        const text = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
                        return text === target;
                    });
                    return candidates.some(el => {
                        const option = el.closest('[class*="option" i],[role="option"]');
                        if (option && visible(option)) return false;
                        for (let current = el, depth = 0; current && depth < 5; current = current.parentElement, depth += 1) {
                            if (isSelected(current)) return true;
                            const cls = String(current.className || '');
                            if (/select|filter|tab/i.test(cls) && norm(current.innerText || current.textContent || '') === target) return true;
                        }
                        return false;
                    });
                };

                const startPath = path();
                const startViewport = viewportSignature();
                const filterGroups = {
                    '普通': ['普通', '竞技'],
                    '竞技': ['普通', '竞技'],
                    'FPP': ['FPP', 'TPP'],
                    'TPP': ['FPP', 'TPP'],
                    '冠军': ['冠军', '全部比赛'],
                    '全部比赛': ['冠军', '全部比赛'],
                };
                const clicks = [];
                const loadingEvents = [];
                const missing = [];
                for (const target of values) {
                    let candidate = bestTarget(target);
                    let openedBy = '';
                    if (!candidate) {
                        for (const alternative of filterGroups[target] || []) {
                            if (alternative === target) continue;
                            const opener = bestTarget(alternative);
                            if (!opener) continue;
                            opener.el.click();
                            openedBy = alternative;
                            await sleep(120);
                            candidate = bestTarget(target);
                            if (candidate) break;
                        }
                    }
                    if (!candidate) {
                        missing.push(target);
                        continue;
                    }
                    candidate.el.scrollIntoView({block: 'nearest', inline: 'nearest'});
                    candidate.el.click();
                    await sleep(70);
                    const currentPath = path();
                    const selectedCandidate = bestTarget(target);
                    const selected = groupSelected(target) || (!!selectedCandidate && (
                        isSelected(selectedCandidate.el)
                        || isSelected(selectedCandidate.el.closest('[role="tab"],button,label,[class*="tab" i],[class*="filter" i]'))
                    ));
                    const loading = loadingState();
                    if (loading.count) loadingEvents.push({target, ...loading});
                    clicks.push({target, selected, openedBy, pathUnchanged: currentPath === startPath, cls: candidate.cls});
                }
                await sleep(120);
                const endViewport = viewportSignature();
                return {
                    values,
                    clicks,
                    missing,
                    startPath,
                    endPath: path(),
                    pathUnchanged: path() === startPath,
                    loadingEvents,
                    finalLoading: loadingState(),
                    viewport: {start: startViewport, end: endViewport},
                    budgetMs,
                };
            }''', {'values': values, 'budgetMs': time_budget_seconds * 1000})
        except Exception as exc:
            return _fail('连续切换筛选失败: ' + str(exc)[:220])

        elapsed_ms = round((time.monotonic() - started) * 1000)
        result['elapsedMs'] = elapsed_ms
        result['withinBudget'] = elapsed_ms <= time_budget_seconds * 1000
        result['allSelected'] = bool(result.get('clicks')) and all(item.get('selected') for item in result['clicks'])
        start_height = int(((result.get('viewport') or {}).get('start') or {}).get('scrollHeight') or 0)
        end_height = int(((result.get('viewport') or {}).get('end') or {}).get('scrollHeight') or 0)
        result['layoutJankObserved'] = bool(start_height and abs(end_height - start_height) > max(600, start_height * 0.45))
        _log(self.execution_record, f'BUSINESS_ACTION nn_rapid_filter_switch evidence={result}')
        if result.get('missing'):
            return _fail('未找到筛选控件: ' + '、'.join(result['missing']), {'detail': result})
        if not result.get('pathUnchanged'):
            return _fail('连续筛选过程中页面路径发生跳转', {'detail': result})
        if not result.get('withinBudget'):
            return _fail(f'连续筛选耗时 {elapsed_ms}ms，超过 {time_budget_seconds} 秒预算', {'detail': result})
        if not result.get('allSelected'):
            return _fail('部分筛选控件点击后未进入选中状态', {'detail': result})
        return _ok(f'已在 {elapsed_ms}ms 内完成 {len(values)} 次筛选切换', {'detail': result})

    async def wait_for_results_idle(self, step) -> ActionResult:
        """Wait for the result region to become quiet without a fixed sleep."""
        timeout_seconds = max(2, int(step.get('timeout_seconds') or 12))
        deadline = time.monotonic() + timeout_seconds
        try:
            await self.page.wait_for_load_state('networkidle', timeout=min(timeout_seconds * 1000, 5000))
        except Exception:
            # SPAs can keep analytics or sockets open. DOM stability is the
            # authoritative fallback for a result list.
            pass

        previous_signature = None
        stable_rounds = 0
        last_probe = {}
        while time.monotonic() < deadline:
            try:
                last_probe = await self.page.evaluate(r'''() => {
                    const visible = el => {
                        const rect = el.getBoundingClientRect();
                        const style = getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < innerHeight
                            && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
                    };
                    const root = document.querySelector('[role="dialog"], [aria-modal="true"], [class*="result" i], [class*="record" i], main') || document.body;
                    const loaders = Array.from(document.querySelectorAll(
                        '[aria-busy="true"],[class*="loading" i],[class*="spinner" i],[class*="skeleton" i],[class*="pending" i]'
                    )).filter(visible);
                    const text = String(root.innerText || root.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 1600);
                    return {loadingCount: loaders.length, signature: `${document.location.href}|${text}|${document.documentElement.scrollHeight}`};
                }''')
            except Exception as exc:
                return _fail('读取结果加载状态失败: ' + str(exc)[:180])
            if last_probe.get('loadingCount') == 0 and last_probe.get('signature') == previous_signature:
                stable_rounds += 1
                if stable_rounds >= 2:
                    return _ok('结果区域请求已结束并稳定', {'detail': {'stableRounds': stable_rounds, **last_probe}})
            else:
                stable_rounds = 0
            previous_signature = last_probe.get('signature')
            await asyncio.sleep(0.3)
        return _fail(f'等待结果区域稳定超时（{timeout_seconds} 秒）', {'detail': last_probe})


async def evaluate_login_success(page) -> Dict[str, Any]:
    try:
        return await page.evaluate(r"""() => {
            const visible = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
            };
            const txt = (el) => (el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('alt') || '').replace(/\s+/g, ' ').trim();
            const bodyText = (document.body && document.body.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 500);
            const loginFormNodes = Array.from(document.querySelectorAll('input,button,a,[role=button]')).filter(visible).filter(el => {
                const t = (txt(el) + ' ' + (el.getAttribute('placeholder') || '') + ' ' + (el.getAttribute('name') || '') + ' ' + (el.getAttribute('type') || '')).toLowerCase();
                return /密码|验证码|请输入手机|手机号|登录|登陆|login|password|captcha|code|mobile|phone/.test(t);
            });
            const passwordInputs = Array.from(document.querySelectorAll('input[type="password"], input[placeholder*="密码"], input[placeholder*="验证码"], input[placeholder*="手机"]')).filter(visible);
            const postLoginNodes = Array.from(document.querySelectorAll('img,[class*="avatar" i],[class*="user" i],[class*="profile" i],[class*="account" i],a,button,[role=button]')).filter(visible).filter(el => {
                const t = txt(el).toLowerCase();
                const cls = (el.className || '').toString().toLowerCase();
                const alt = (el.getAttribute('alt') || '').toLowerCase();
                return /退出|注销|个人中心|用户中心|我的主页|账号中心|logout|sign out|profile|avatar/.test(t + ' ' + cls + ' ' + alt);
            });
            const storageHits = [];
            const strongStorageHits = [];
            const stores = [];
            try { stores.push(localStorage); } catch (_) {}
            try { stores.push(sessionStorage); } catch (_) {}
            for (const store of stores) {
                for (let i = 0; i < store.length; i++) {
                    const k = store.key(i) || '';
                    const v = store.getItem(k) || '';
                    if (/(token|auth|login|user|session|jwt)/i.test(k) && v && v !== 'null' && v !== 'undefined') storageHits.push(k);
                    if (/^(?:userId|h5_userInfo|accessToken|authToken|token|jwt)$/i.test(k) || /^lastUserActivityReport_\d+$/i.test(k)) {
                        if (v && !/^(?:null|undefined|-1|0|\{\}|\[\])$/i.test(v.trim())) strongStorageHits.push(k);
                    }
                }
            }
            const loginDialogs = Array.from(document.querySelectorAll('[role="dialog"],.ui-dialog,.nn-dialog,.nn-modal,.modal,.dialog'))
                .filter(visible)
                .filter(el => /登录|登陆|手机号|验证码|手机验证码/.test(txt(el)) && el.querySelectorAll('input').length > 0);
            const hasLoginForm = passwordInputs.length > 0 || loginFormNodes.length >= 2 || loginDialogs.length > 0;
            const guestGate = /当前浏览状态[，,]?\s*关注后可参与互动|您已在其他地方登录|登录已失效|请先登录/.test(bodyText);
            const hasPostLogin = postLoginNodes.some(el => txt(el).length > 0);
            const hasAuthStorage = strongStorageHits.length > 0;
            // Generic user/cache keys can survive logout. Only named account UI
            // or strong post-login storage keys count as a live session signal.
            const passed = !hasLoginForm && !guestGate && (hasPostLogin || hasAuthStorage);
            return {passed, reason: passed ? '' : (hasLoginForm ? '页面仍存在登录表单/账号密码验证码输入框' : (guestGate ? '页面展示游客态/登录失效提示' : '未检测到头像/用户中心/退出入口或有效登录 token')), evidence: {url: location.href, title: document.title, loginFormCount: loginFormNodes.length, passwordInputCount: passwordInputs.length, loginDialogCount: loginDialogs.length, postLoginCount: postLoginNodes.length, postLoginSamples: postLoginNodes.slice(0, 5).map(txt), storageKeys: storageHits.slice(0, 10), strongStorageKeys: strongStorageHits.slice(0, 10)}, bodyText};
        }""")
    except Exception as exc:
        return {'passed': False, 'reason': '登录态检测异常: ' + str(exc)[:200], 'evidence': {}, 'bodyText': ''}


async def execute_business_action(page, step, execution_record=None, permission_cleanup=None) -> ActionResult:
    actions = NNPageActions(page, execution_record)
    name = step.get('business_action')
    if name == 'nn_grant_permission':
        return await actions.grant_permission(step, permission_cleanup=permission_cleanup)
    if name == 'nn_revoke_permission':
        return await actions.revoke_permission(step)
    if name == 'nn_open_login':
        return await actions.open_login(step)
    if name == 'nn_fill_phone':
        return await actions.fill_phone(step)
    if name == 'nn_fill_verification_code':
        return await actions.fill_verification_code(step)
    if name == 'nn_fill_password':
        return await actions.fill_password(step)
    if name == 'nn_submit_login':
        return await actions.submit_login(step, require_success=False)
    if name == 'nn_complete_login':
        return await actions.submit_login(step, require_success=True)
    if name == 'nn_hall_fill_message':
        return await actions.fill_hall_message(step)
    if name == 'nn_hall_send_message':
        return await actions.send_hall_message(step)
    if name == 'nn_hall_open_emoji_panel':
        return await actions.open_hall_emoji_panel(step)
    if name == 'nn_hall_close_emoji_panel':
        return await actions.close_hall_emoji_panel(step)
    if name == 'nn_hall_select_emoji':
        return await actions.select_hall_emoji(step)
    if name == 'nn_hall_send_selected_emoji':
        return await actions.send_selected_hall_emoji(step)
    if name == 'nn_hall_close_top_ad':
        return await actions.close_hall_top_ad(step)
    if name == 'nn_hall_close_message_menus':
        return await actions.close_hall_message_menus(step)
    if name == 'nn_hall_open_invite_share':
        return await actions.open_hall_invite_share(step)
    if name == 'nn_hall_close_invite_share':
        return await actions.close_hall_invite_share(step)
    if name == 'nn_hall_verify_retract_notice':
        return await actions.verify_hall_retract_notice(step)
    if name == 'nn_hall_search_member':
        return await actions.search_hall_member(step)
    if name == 'nn_hall_verify_member_search':
        return await actions.verify_hall_member_search(step)
    if name == 'nn_hall_verify_member_empty_state_layout':
        return await actions.verify_hall_member_empty_state_layout(step)
    if name == 'nn_hall_verify_hall_route':
        return await actions.verify_hall_route(step)
    if name == 'nn_hall_verify_member_search_layout_health':
        return await actions.verify_hall_member_search_layout_health(step)
    if name == 'nn_hall_verify_channel_controls':
        return await actions.verify_hall_channel_controls(step)
    if name == 'nn_hall_clear_member_search':
        return await actions.clear_hall_member_search(step)
    if name == 'nn_hall_reply_runtime_message':
        return await actions.reply_hall_runtime_message(step)
    if name == 'nn_hall_cancel_reply':
        return await actions.cancel_hall_reply(step)
    if name == 'nn_hall_retract_runtime_message':
        return await actions.retract_hall_runtime_message(step)
    if name == 'nn_hall_retract_runtime_messages':
        reply = await actions.retract_hall_runtime_message({**step, 'message_role': 'reply'})
        if reply.get('status') != 'completed':
            return reply
        return await actions.retract_hall_runtime_message({**step, 'message_role': 'original'})
    if name == 'nn_open_top_search':
        # A standalone open step must perform and verify the click.  Reporting
        # success without opening the popup hid real click failures from later steps.
        return await actions.top_community_search({**step, 'open_only': True})
    if name == 'nn_top_community_search':
        return await actions.top_community_search(step)
    if name == 'nn_open_recruitment':
        return await actions.open_recruitment(step)
    if name == 'nn_submit_recruitment':
        return await actions.submit_recruitment(step)
    if name == 'nn_click_community_result':
        return await actions.click_community_result(step)
    if name == 'nn_click_identity_card':
        return await actions.click_identity_card(step)
    if name == 'nn_query_battle_records':
        return await actions.query_battle_records(step)
    if name == 'nn_switch_chicken_rank_periods':
        return await actions.switch_chicken_rank_periods(step)
    if name == 'nn_rapid_filter_switch':
        return await actions.rapid_filter_switch(step)
    if name == 'nn_wait_for_results_idle':
        return await actions.wait_for_results_idle(step)
    if name == 'nn_switch_home_banner':
        return await actions.switch_home_banner(step)
    if name == 'nn_click_community_plugin':
        return await actions.click_community_plugin(step)
    if name == 'nn_open_article_detail':
        return await actions.open_article_detail(step)
    if name == 'nn_close_article_detail':
        return await actions.close_article_detail(step)
    if name == 'nn_focus_article_comment':
        return await actions.focus_article_comment(step)
    if name == 'nn_fill_article_comment':
        return await actions.fill_article_comment(step)
    if name == 'nn_open_article_management':
        return await actions.open_article_management(step)
    if name == 'nn_open_article_draft_for_edit':
        return await actions.open_article_draft_for_edit(step)
    if name == 'nn_open_article_published_for_edit':
        return await actions.open_article_published_for_edit(step)
    if name == 'nn_delete_article_draft':
        return await actions.delete_article_draft(step)
    if name == 'nn_delete_published_article':
        return await actions.delete_published_article(step)
    if name == 'nn_delete_all_current_user_published_articles':
        return await actions.delete_all_current_user_published_articles(step)
    if name == 'nn_confirm_article_draft_delete':
        return await actions.confirm_article_draft_delete(step)
    if name == 'nn_verify_article_draft_absent':
        return await actions.verify_article_draft_absent(step)
    if name == 'nn_verify_article_published':
        return await actions._verify_article_published_present()
    if name == 'nn_verify_published_article_absent':
        return await actions.verify_published_article_absent(step)
    if name == 'nn_open_article_editor':
        return await actions.open_article_editor(step)
    if name == 'nn_select_article_type':
        return await actions.select_article_type(step)
    if name == 'nn_verify_article_type_immutable':
        return await actions.verify_article_type_immutable(step)
    if name == 'nn_close_article_editor':
        return await actions.close_article_editor(step)
    if name == 'nn_submit_article':
        return await actions.submit_article(step)
    if name == 'nn_save_article_draft':
        return await actions.submit_article(step, save_as_draft=True)
    if name == 'nn_fill_article_title':
        return await actions.fill_article_field(step, 'title')
    if name == 'nn_fill_article_body':
        return await actions.fill_article_field(step, 'body')
    if name == 'nn_append_article_body':
        return await actions.append_article_body(step)
    if name == 'nn_click_popular_tag':
        try:
            result = await page.evaluate(r'''() => {
                const visible = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden'; };
                const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
                const label = Array.from(document.querySelectorAll('div,span,p,label')).find(el => visible(el) && norm(el.innerText || el.textContent).startsWith('热门引用'));
                if (!label) return {found: false, reason: '未找到热门引用区域'};
                const root = label.parentElement && label.parentElement.parentElement || label.parentElement;
                const candidates = Array.from(root.querySelectorAll('button,a,[role="button"],span,div')).filter(el => visible(el) && el !== label && norm(el.innerText || el.textContent).length > 0 && norm(el.innerText || el.textContent).length <= 40);
                const target = candidates.find(el => /cursor-pointer|button|tag|chip/i.test(String(el.className || ''))) || candidates[0];
                if (!target) return {found: false, reason: '热门引用区域没有可点击标签'};
                const text = norm(target.innerText || target.textContent);
                target.click();
                return {found: true, text, cls: String(target.className || '').slice(0, 160)};
            }''')
            if result and result.get('found'):
                return _ok('已点击热门引用标签', result)
            return _fail((result or {}).get('reason') or '未找到热门引用标签', result)
        except Exception as exc:
            return _fail('点击热门引用标签失败: ' + str(exc)[:200])
    return _fail(f'未知业务动作: {name}')
