---
title: "Five small bugs, one critical chain — anatomy of a 1-click account takeover"
description: "How a permissive deeplink router, an App Link bridge, a javascript: scheme whitelist, an Intent.parseUri sink, and an authenticated WebView combine into a 1-click account takeover — and how a chain correlator surfaces it as one CRITICAL."
published: 2026-07-07
author: Jackson Mafra
tags: ["mobile-security", "android", "vulnerability-chain", "deeplinks", "webview"]
canonical: https://mnexus.vercel.app/articles/05-five-small-bugs-one-critical-chain
codex_refs:
  - "Common Bypasses — https://medium.com/@jacksonfdam/"
  - "Content-Provider Exploitation — https://medium.com/@jacksonfdam/"
medusa_refs:
  - https://github.com/jacksonfdam/medusa-nexus
tldr: |
  Five individually-mild Android bugs — a permissive scheme router, an App Link bridge,
  a javascript: scheme in a WebView whitelist, an Intent.parseUri call in
  shouldOverrideUrlLoading, and a WebView that attaches auth headers without host
  validation — chain into a one-click account takeover. Each bug, on its own, would
  rate MEDIUM at worst. The chain rates CRITICAL. The chain correlator's job is to
  see what isolated detectors cannot.
---

The most consequential finding in a mobile audit is rarely a single bug. It's a sequence — five or six small issues, individually mild, that combine into something that lets an attacker take over a user account with one tap on a malicious link. Every detector built into MedusaNexus, taken alone, would rate the individual issues at LOW or MEDIUM severity. The chain — the *sequence* — rates CRITICAL.

This article walks through one such chain in detail. The pattern is real; the variations are common; the chain correlator that surfaces it lives at `mnexus/intelligence/chain_correlator.py` in the open-source repository. By the end of the article, you should be able to recognize the shape of the chain in a static report, understand what each link contributes, and know which single link to break to neutralize the whole sequence.

The chain has five links. Each one is a small bug. Together they produce a one-click attack.

## The attack in one paragraph

The victim clicks a link in their browser. The link opens the target app via an App Link intent-filter. The App Link handler extracts an embedded URI from a query parameter and forwards it into the app's internal scheme router. The internal scheme router dispatches to a WebView handler that loads a URL without host validation. The URL is a `javascript:` URL — explicitly whitelisted in the WebView's scheme allowlist — that runs arbitrary JavaScript in the WebView's context. The JavaScript redirects the WebView to an `intent://` URL. The WebView's `shouldOverrideUrlLoading` callback parses the intent with `Intent.parseUri()` and starts a second activity — an authenticated WebView meant for internal account pages. The second WebView loads an attacker-controlled URL, attaches the user's session tokens (cookies, Authorization header, custom headers) without checking the host, and ships them to the attacker.

Five links. One critical finding. Every one of them is a static-analysis flag that's well within the reach of a developer's audit. The problem isn't that any one of them is hard to find — it's that no isolated detector flags the chain.

## Link 1 — Permissive deeplink router

The first link is the entry point. The app declares a custom scheme, say `myapp://`, with a handful of hosts in its `AndroidManifest.xml`:

```xml
<activity android:name=".MainActivity" android:exported="true">
  <intent-filter>
    <action android:name="android.intent.action.VIEW" />
    <category android:name="android.intent.category.DEFAULT" />
    <category android:name="android.intent.category.BROWSABLE" />
    <data android:scheme="myapp" android:host="home" />
    <data android:scheme="myapp" android:host="settings" />
    <data android:scheme="myapp" android:host="profile" />
  </intent-filter>
</activity>
```

Three hosts declared. Reasonable. The problem appears when you decompile `MainActivity` and look at the deeplink handling:

```java
public void onCreate(Bundle b) {
    Uri data = getIntent().getData();
    String host = data.getHost();
    DeeplinkHandler handler = ROUTES.get(host);   // ← map lookup
    if (handler != null) {
        handler.execute(data);
    }
}

static final Map<String, DeeplinkHandler> ROUTES = Map.of(
    "home",        new HomeHandler(),
    "settings",    new SettingsHandler(),
    "profile",     new ProfileHandler(),
    "popupPanel",  new PopupSheetHandler(),       // ← not in manifest
    "webview",     new WebViewHandler(),          // ← not in manifest
    "deeplink",    new DeeplinkRedirector(),      // ← not in manifest
    "purchase",    new PurchaseHandler(),         // ← not in manifest
    // … 80+ more
);
```

The map has eighty-plus entries. The manifest declares three. The other eighty-plus handlers are reachable — from any process on the device that can send the right intent — but invisible from the manifest. They're *hidden surface*.

MedusaNexus's `DeeplinkRouterAudit` detector (at `mnexus/intelligence/deeplink_audit.py`) flags this pattern by comparing the set of hosts that appear in `surface.deeplinks` against the set of hosts declared in `surface.exported_components`. When the gap is wider than 30%, a finding fires. With eighty hidden routes against three declared, the finding rates HIGH on its own.

**Why it's MEDIUM-shaped on its own**: an attacker on the device can reach the hidden handlers, but they need to already have malware installed to send the intent. The risk surface is real but bounded.

**Why it matters in the chain**: it's the entry point. Without the bridge in link 2, the hidden routes need a local app to reach. With the bridge, they become browser-reachable.

## Link 2 — The App Link bridge

The second link is what upgrades the local exploit to a 1-click attack. The same `MainActivity` declares another intent-filter, this time for an App Link:

```xml
<intent-filter android:autoVerify="true">
  <action android:name="android.intent.action.VIEW" />
  <category android:name="android.intent.category.DEFAULT" />
  <category android:name="android.intent.category.BROWSABLE" />
  <data android:scheme="https" android:host="applink.myapp.com" />
  <data android:scheme="https" android:host="applink.myapp.com" android:pathPrefix="/open" />
</intent-filter>
```

App Links are HTTPS URLs that are verified via the [Digital Asset Links protocol](https://developers.google.com/digital-asset-links/v1/getting-started) — Android confirms the developer's ownership of the domain before letting the URL open the app instead of the browser. The verification is a good thing; it's what makes App Links secure entry points compared to custom schemes.

The problem is what `MainActivity` does when it receives the App Link:

```java
if (uri.getHost().equals("applink.myapp.com")) {
    String page = uri.getQueryParameter("page");
    if (page != null) {
        Uri inner = Uri.parse(page);
        handleDeeplink(inner);   // ← re-enters the scheme router
    }
}
```

The handler extracts the `page` query parameter, parses it as a URI, and feeds it back into the same scheme router from link 1. That means `https://applink.myapp.com/open?page=myapp://popupPanel?url=…` opens `MainActivity` (App Link verified) → extracts `page` → calls `handleDeeplink(myapp://popupPanel?url=…)` → reaches the hidden `popupPanel` handler.

The browser just triggered a deeplink that was supposed to be internal-only.

MedusaNexus's `AppLinkBridgeDetector` flags this pattern by detecting two signals: an exported activity declaring an https intent-filter with a path like `/open`, `/deeplink`, `/page`, `/redirect`, *and* deeplinks in the surface that carry inner-deeplink query parameters (`?page=…`, `?url=…`, `?deeplink=…`). Either signal alone is suspicious; both together make the finding HIGH severity.

**Why it's HIGH-shaped on its own**: bridge handlers are open redirects in spirit, even without the rest of the chain. They violate the principle that App Link verification is supposed to restrict the entry points, not multiply them.

**Why it matters in the chain**: it converts the local-only exploit from link 1 into a browser-triggerable attack. Every other link in the chain inherits the browser-reachable property from this one.

## Link 3 — The dangerous-scheme whitelist

The third link is inside the WebView the popup-panel handler opens. When the handler receives the URL parameter, it ends up calling something like:

```java
public class ContentWebView extends WebView {
    @Override
    public void loadUrl(String url) {
        if (isForeignHost(url) || !hasValidScheme(url)) {
            return;
        }
        super.loadUrl(url, getAuthHeaders());
    }

    private boolean hasValidScheme(String url) {
        String scheme = Uri.parse(url).getScheme();
        return PERMITTED.contains(scheme);
    }

    static final Set<String> PERMITTED =
        Set.of("http", "https", "javascript", "data");  // ← javascript whitelisted
}
```

The `javascript` scheme is explicitly in the allowlist. The reason this exists is, almost always, legitimate at first sight — the developers wanted to use `loadUrl("javascript:foo()")` from native code to invoke JS in the WebView. But the side effect is that *any* `javascript:…` URL that reaches `loadUrl` will execute as JavaScript in the WebView's context — including JavaScript controlled by an attacker who reached this code via links 1 and 2.

MedusaNexus's WebView scheme audit detector (in the WebView audit suite) flags this pattern by scanning decompiled WebView subclasses for scheme allowlists and reporting any entry from `{javascript, file, content, data, intent}`. Each whitelisted dangerous scheme is one HIGH finding.

**Why it's HIGH-shaped on its own**: any WebView that allows `javascript:` URLs from external input is an XSS-in-native-app primitive. Even without the rest of the chain, an attacker who can reach the WebView with a `javascript:` URL has runtime JS execution.

**Why it matters in the chain**: this is where the attacker gets arbitrary JavaScript execution. From here, they can use the JavaScript to navigate the WebView wherever they want.

## Link 4 — Intent.parseUri in shouldOverrideUrlLoading

The fourth link is what turns the JavaScript execution from link 3 into an Intent injection. The WebView's client overrides `shouldOverrideUrlLoading` — the method called when the WebView is about to navigate to a new URL:

```java
public class ContentWebViewClient extends WebViewClient {
    @Override
    public boolean shouldOverrideUrlLoading(WebView view, String url) {
        if (url.startsWith("intent://")) {
            try {
                Intent intent = Intent.parseUri(url, Intent.URI_INTENT_SCHEME);
                view.getContext().startActivity(intent);
                return true;
            } catch (URISyntaxException e) {
                return false;
            }
        }
        return false;
    }
}
```

`Intent.parseUri` is a built-in Android API that parses an `intent://` URL into a fully-formed `Intent` object — including the target component, the action, the extras, the flags. *Anything* the URL specifies, `parseUri` constructs. When `startActivity` is called on the parsed intent, the system launches whatever activity the URL named — including internal activities that were never intended to be launchable from a WebView.

MedusaNexus's intent-redirect detector flags this pattern by scanning WebViewClient subclasses for `Intent.parseUri` calls inside `shouldOverrideUrlLoading`. When the call isn't followed by a `getPackage()` or `getComponent()` check, the finding rates CRITICAL.

**Why it's CRITICAL-shaped on its own**: this *is* an intent-redirection vulnerability without needing the rest of the chain. An attacker with any JavaScript-execution primitive in the WebView can launch arbitrary internal activities.

**Why it matters in the chain**: it's the pivot. The JavaScript from link 3 redirects the WebView to an `intent://` URL; `parseUri` constructs an intent; `startActivity` launches whichever internal activity the attacker chose. The link 5 activity is the one they choose.

## Link 5 — Authenticated WebView with no host check

The fifth link is the sink — the activity the chain ultimately targets. The app has a separate WebView activity used for authenticated, account-related pages:

```java
public class AccountHubActivity extends Activity {
    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        WebView wv = new WebView(this);
        wv.getSettings().setJavaScriptEnabled(true);
        setContentView(wv);

        String url = getIntent().getStringExtra("url");
        Map<String, String> headers = AuthHeaders.forCurrentSession();
        wv.loadUrl(url, headers);   // ← loads any URL with auth headers attached
    }
}
```

`AccountHubActivity` reads a URL from the launching intent's `"url"` extra, builds the authenticated header map (cookies, Authorization Bearer, custom session headers), and calls `loadUrl(url, headers)`. There is no check on the URL's host. There is no allowlist of trusted domains. The activity assumes the URL has been validated upstream — but in the chain, the upstream is the attacker.

MedusaNexus's authenticated-WebView audit detector flags this pattern by scanning for WebView activities that attach auth headers via `loadUrl(url, headers)` without a preceding host-check call. When the activity is exported (or, as in this case, reachable via an intent-redirect from another exported activity), the finding rates CRITICAL.

**Why it's CRITICAL-shaped on its own**: any activity that loads attacker-controlled URLs while attaching session credentials is a credential-exfiltration primitive. The bug exists independently of the rest of the chain.

**Why it matters in the chain**: it's where the user's tokens leave. The chain ends here — the attacker's URL receives the session credentials, and the account takeover is complete.

## The chain correlator

Each of the five links, individually, would surface in MedusaNexus as its own finding. A scan against the vulnerable APK would produce something like:

```
🔱 nexus PRJ-… ❯ /findings high
┌──────────────┬──────────┬────────────────────┬───────────────────────────────────────────┐
│ id           │ sev      │ engine             │ title                                      │
├──────────────┼──────────┼────────────────────┼───────────────────────────────────────────┤
│ FND-7B22A91C │ HIGH     │ deeplink_audit     │ Permissive deeplink router for scheme...   │
│ FND-A8E1F02C │ HIGH     │ deeplink_audit     │ App Link bridge re-dispatches into...      │
│ FND-3C9D4B11 │ HIGH     │ webview_audit      │ WebView whitelist allows javascript: URLs  │
│ FND-D17E0066 │ CRITICAL │ webview_audit      │ Intent.parseUri in shouldOverrideUrlLoad...│
│ FND-AA12F45E │ CRITICAL │ webview_audit      │ Authenticated WebView loads URLs without...│
└──────────────┴──────────┴────────────────────┴───────────────────────────────────────────┘
```

Five findings, three HIGH and two CRITICAL. A developer reading the list might prioritize the two CRITICALs and miss the fact that the *combination* of all five is what creates the 1-click attack. The CRITICALs without the HIGHs are still bad — but they require local code execution to exploit. The HIGHs convert them into browser-reachable.

That's the chain correlator's job. After the engine fan-out and the standard correlation pass, the chain correlator pattern-matches against known attack-chain templates. Each template specifies a set of finding signatures that, when present together, constitute a chain:

```python
ATO_1CLICK_CHAIN = ChainTemplate(
    name="1-click_account_takeover_via_deeplink_chain",
    severity=Severity.CRITICAL,
    requires=[
        any_of("applink_bridge_detected", "browsable_scheme_router"),
        "webview_handler_no_host_validation",
        any_of("webview_scheme_javascript_allowed",
               "webview_scheme_file_allowed",
               "webview_scheme_intent_allowed"),
        "intent_redirect_in_webview_client",
        "authed_webview_loads_unchecked_url",
    ],
)
```

When every requirement matches against the project's findings, the correlator emits a single CRITICAL chain finding:

```
🔱 nexus PRJ-… ❯ /findings critical
┌──────────────┬──────────┬─────────────────┬──────────────────────────────────────────┐
│ FND-CHAIN001 │ CRITICAL │ chain_correlator│ 1-click account takeover via deeplink     │
│              │          │                 │ chain (5 contributing findings)           │
└──────────────┴──────────┴─────────────────┴──────────────────────────────────────────┘
```

The chain finding's evidence section links to every contributing finding. The remediation section enumerates which single link to break — fixing any one of them neutralizes the chain — and the trade-offs of each choice.

## Breaking the chain — which link to fix

Five links, five potential fix points. Not all are equally good.

* **Link 1 — Permissive deeplink router.** Fixing this means trimming the hidden handlers down to the ones explicitly intended for external invocation, and declaring them all in the manifest. Highest cost (touches a lot of code), highest value (closes other attack vectors not in this chain).
* **Link 2 — App Link bridge.** Fixing this means validating the `page` parameter against a strict allowlist before re-dispatching. Lower cost (one method), still high value (closes any chain that depends on the bridge).
* **Link 3 — javascript: whitelist.** Fixing this means removing `javascript` from the WebView's scheme allowlist. Lowest cost (one line), but might break a legitimate internal use case if developers were depending on the side effect.
* **Link 4 — Intent.parseUri.** Fixing this means replacing the `parseUri` call with an explicit allowlist of internal activities the WebView is allowed to launch. Medium cost, medium value.
* **Link 5 — Authenticated WebView host check.** Fixing this means adding a host-allowlist check before calling `loadUrl(url, headers)` in any authenticated WebView. Low cost, high value, and it closes a category of bug that comes back constantly (any future authenticated WebView inherits the protection).

MedusaNexus's chain remediation block lists all five with the trade-offs, in order of "lowest cost first, highest value first." For most teams, the right answer is to fix links 2, 3, *and* 5 — defence in depth, three independent fixes, any one of which breaks the chain. The CRITICAL becomes a non-finding after any one of them; fixing three eliminates the *category*.

## Other chains the correlator catches

The 1-click ATO chain isn't the only template. The catalogue in `mnexus/intelligence/chain_correlator.py` includes:

* **`task_hijacking_chain`** — `taskAffinity` + `launchMode="singleTask"` + exported = an activity that can be moved to a malicious task, with the user's UI history attached. The Codex entry on *Common Bypasses* covers the attacker techniques.
* **`cleartext_token_leak_chain`** — `usesCleartextTraffic=true` + a hard-coded HTTP URL + an `Authorization` header attached to that URL's requests. Credentials leak in plaintext over the wire.
* **`pendingintent_hijack_chain`** — a mutable `PendingIntent` with an action exposed to other apps. The classic *intent hijack* on Android 12+.
* **`provider_path_traversal_chain`** — an exported `ContentProvider` + `grantUriPermissions=true` + path traversal in the `openFile` implementation. The Codex entry on *Content-Provider Exploitation* dissects this pattern.

Every template is one Python class. Each can be added in roughly 30 lines. The catalogue is open-source; the patterns are catchable.

## TL;DR

The 1-click ATO chain has five links: permissive deeplink router, App Link bridge, javascript-scheme whitelist, `Intent.parseUri` in `shouldOverrideUrlLoading`, and an authenticated WebView that loads URLs without host validation. Each link, individually, would rate HIGH at most. The chain rates CRITICAL because it lets an attacker take over a user's account with a single tap.

The chain correlator's contribution is *pattern matching across findings* — recognizing that a particular combination is dangerous even when each individual finding looks manageable. Breaking any single link neutralizes the entire chain; fixing three breaks the *category*.

The pattern is real. The variations are common. Every detector in the chain is implementable in under a hundred lines. The correlator that ties them together is the leverage; that's the layer the platform builds itself, on top of the five engines from article 4.

> The hardest part of mobile security audits is not finding individual bugs — it's recognizing when bugs combine. The bugs in this article would each be fixable in a sprint; the chain has been shipping in production apps for years because no isolated detector flagged it. A chain correlator is the cheapest investment that closes that gap.

---

**Next in the series →** *Shift-left mobile security — block bad commits with one YAML.* How to wire MedusaNexus into a CI/CD pipeline so the chain detection in this article runs on every commit, blocks merges when new CRITICAL findings appear, and turns the security team's report into a build-time check.

---

*The series continues weekly on [Medium](https://medium.com/@jacksonfdam/). For deeper coverage of attacker techniques — `Common Bypasses`, `Content-Provider Exploitation` — see the Codex at [Umain Fortress](https://umain-fortress.vercel.app/).*
