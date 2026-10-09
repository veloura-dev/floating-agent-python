# FRONTEND_SKILL.md

## Professional Frontend Agent Operating Standard

**Purpose:** Give an AI agent a repeatable, platform-aware way to plan, design, implement, test, and hand off polished frontend experiences for websites, web applications, progressive web apps (PWAs), and mobile applications.

**Audience:** An AI coding/design agent working in an existing repository or starting a new frontend project.

**Scope:** Product UX, information architecture, visual direction, responsive composition, accessible interaction, frontend architecture and code, performance, testing, and handoff. This skill complements—not replaces—repository instructions, platform design guidance, security requirements, or the general software-development protocol in `DEVELOPMENT_SKILL.md`.

**Research basis:** Apply the principles in `UI_UX_FRONTEND_DESIGN_RESEARCH.md`. It distinguishes durable standards and evidence-based practice from optional 2026 trend signals. Platform and browser support changes; verify current official documentation when implementation depends on a version-sensitive feature.

> **Core instruction:** Build for the people, task, content, and platform—not for a trend or an imagined screenshot. A successful frontend is coherent, useful, accessible, responsive, maintainable, and demonstrably functional. Visual polish is important, but it cannot compensate for a broken task or inaccessible control.

### Normative language

- **MUST** means a baseline requirement unless the user, platform, or repository explicitly imposes a stricter rule.
- **SHOULD** means the default professional practice; deviate when evidence or constraints justify it and record the reason for consequential choices.
- **MAY** means an optional technique. A visual trend is never a requirement by itself.

---

## 1. Mission and definition of done

The agent must deliver the smallest complete frontend solution that meets the user’s real need, fits the existing codebase, and behaves well in the contexts where it will be used. Do not mistake “the page renders” or “the screenshot looks attractive” for completion.

A frontend task is done only when all applicable checks are true:

1. The requested product, audience, platform, primary task, scope, and acceptance criteria are understood—or conservative assumptions are stated.
2. Existing project instructions, stack, routes, components, assets, and working state have been inspected before editing.
3. The information architecture and key user flow make sense before decorative effects are added.
4. The implementation follows project conventions and uses suitable platform semantics and controls.
5. The interface adapts to supported viewports, content lengths, input methods, and states.
6. Keyboard, assistive-technology, contrast, focus, zoom, and motion requirements have been considered and tested proportionately.
7. Loading, empty, success, error, offline, unavailable, and permission states are handled where relevant—not just the happy path.
8. Relevant tests, lint/type checks, production build, and manual browser/device checks have run, or unrun checks are named honestly.
9. No placeholder text, broken links, console errors, accidental secrets, unnecessary dependencies, or unrelated edits remain.
10. The handoff states what changed, what was validated, important assumptions, and known limitations.

Never claim a visual, accessibility, device, or performance check passed unless it actually ran. Do not claim full WCAG conformance from an automated scan or a few spot checks.

---

## 2. Non-negotiable principles

1. **Start with the task.** Translate “make it modern” or “improve the UI” into a target audience, user need, primary job, context, constraints, and observable outcome.
2. **Evidence before preference.** Use research, existing product data, user feedback, and realistic task testing where available. A stakeholder’s or agent’s aesthetic preference is not user evidence.
3. **Use the simplest fitting solution.** Keep the existing stack and design conventions unless a change is justified. Do not add a framework, animation library, design system, or global state tool just because it is fashionable.
4. **Design content and behavior together.** Real labels, names, dates, errors, translated strings, and long values affect layout. Do not finalize a design with only ideal placeholder content.
5. **Accessibility is part of the architecture.** Use semantic structure, native controls, keyboard support, visible focus, clear labels, adequate contrast, and reduced-motion alternatives from the start.
6. **Responsive is a behavior, not a device mockup.** Make content and controls work as space, orientation, input method, text size, and user settings change.
7. **Trends are optional treatments.** Bento layouts, glass effects, neumorphism, gradients, 3D, dark-first palettes, and scroll animation must earn their place by helping the actual product.
8. **Prefer robust behavior over fragile spectacle.** The experience must remain legible and usable if an image fails, an effect is unsupported, the network is slow, JavaScript is delayed, or a user has enabled accessibility settings.
9. **Protect trust and user control.** Be clear about cost, consequences, consent, data, and system status. Do not create deceptive UI, coercive defaults, or dark patterns.
10. **Inspect and validate.** Read before editing; run the app; inspect rendered output; test important interactions; review the final diff.

---

## 3. End-to-end agent protocol

Scale this workflow to the risk and size of the task. A small component change still needs inspection and relevant verification; a new product needs the full loop.

### Phase 0 — Establish the working context

1. Confirm the deliverable, workspace/repository, user constraints, and any references or attachments.
2. Read project-level and folder-level instructions before editing. Inspect version-control status if available; preserve pre-existing user changes.
3. Identify the product type, routes/screens, framework, build tooling, styling method, supported browsers/devices, and how to run the project from its actual configuration.
4. Inspect existing design tokens, components, assets, fonts, icons, page patterns, tests, and responsive conventions. Reuse good existing work.
5. Run the current app and a narrow baseline check when practical. Separate pre-existing failures from anything introduced by the task.

**Gate:** Know what may safely change, what must be preserved, and how the result can be run and checked.

### Phase 1 — Convert the request into a task brief

Capture these items in a short working brief:

- **Outcome:** What must the user be able to see or do?
- **Audience and context:** Who uses it, where, how often, and with what devices, connectivity, language, ability, and input method?
- **Primary task:** What is the most important user journey? What are secondary tasks?
- **Content and data:** What information, actions, statuses, and validation rules are real requirements?
- **Platform:** Website, web app, PWA, native iOS/Android, cross-platform mobile, or an explicit combination?
- **Constraints:** Existing stack, brand, accessibility target, browser support, API, deadlines, privacy, performance, or legal requirements.
- **Success measures:** What user outcome and guardrails show success?
- **Out of scope and assumptions:** What should not change? Which uncertainties can be safely resolved by an assumption?

Ask a focused question when a missing answer would materially change the platform, data handling, public behavior, visual direction, or architecture. Otherwise proceed with a conservative assumption and state it in the handoff. Do not ask the user to choose technical details that the repository or project requirements already settle.

### Phase 2 — Reconnaissance and user-flow plan

1. Map the relevant routes/screens and reusable parts.
2. Identify the entry point, user goal, decision points, primary action, alternate paths, and exit/success state.
3. List required states: initial, loading, loaded, empty, invalid, error, offline, permission-denied, disabled, success, and any product-specific state.
4. Record important content hierarchy and navigation needs. Distinguish navigation from an action, a disclosure, a tab set, and a modal dialog.
5. Map every acceptance criterion to an implementation and a verification method.
6. Identify risks: inaccessible custom controls, sensitive data, layout fragility, animation, third-party assets, rendering cost, browser support, and API failure.

Use a compact flow when it helps:

```text
Entry → orient → understand options → act → receive feedback
                         ↘ recover / edit / cancel ↗
                         → confirm completion → useful next step
```

This is a design aid, not a requirement that every page have a wizard or extra step.

### Phase 3 — Choose the platform and architecture

Use the platform the user requested and the one the existing product can support. Do not treat a responsive website, PWA, and native mobile app as interchangeable.

| Product need | Suitable direction to evaluate | Important considerations |
|---|---|---|
| Content-led public site, campaign, documentation, publication | Semantic HTML with an appropriate static or server-rendered framework | Reading order, SEO, fast first render, content management, accessible navigation, shareable URLs |
| Highly interactive application with data and authenticated workflows | The repository’s established application framework and routing/data patterns; server/client rendering as appropriate | State ownership, permissions, loading/error states, deep links, forms, data freshness, bundle and rendering cost |
| Installable web experience or useful offline access | PWA capabilities only when they solve a real user need | Offline cache rules, stale data, update behavior, install value, graceful browser fallback, privacy and storage |
| iOS/Android app | Native platform UI or an established cross-platform stack selected for project needs | Platform conventions, accessibility tree, safe areas, keyboard behavior, lifecycle, store/device capabilities, offline and permission flows |
| Shared web and mobile product | Shared domain logic and design tokens where useful; adapt interaction patterns to each platform | Do not force pixel-identical layouts or web navigation patterns into native contexts |

Decision rules:

- In an existing repository, follow its framework, package manager, naming, routing, styling, and component patterns unless they block the stated goal.
- In a new project, choose rendering and framework from content needs, SEO, interactivity, team capability, hosting, runtime, accessibility, and maintainability—not from trend rankings.
- Use native platform controls and idioms when they improve expected behavior or accessibility. For native details, check current official Apple/Android/platform guidance; do not invent exact platform requirements.
- Make custom controls only when a native element cannot satisfy a real need. A custom widget requires the complete keyboard, focus, role, state, and assistive-technology behavior.
- Keep client code free of secrets and privileged credentials. Authentication and authorization must be enforced by trusted services, not merely hidden UI.

### Phase 4 — Plan the experience and visual system

Before styling, record:

- Page/screen purpose and title.
- Primary user task and primary action (if the screen needs one).
- Information priority: what must be noticed first, what supports a decision, and what can be secondary.
- Navigation model and active/current location.
- Content inventory, important edge cases, and state copy.
- Layout family and responsive behavior.
- Brand tone, palette roles, type hierarchy, imagery, depth, and motion.
- Accessibility, performance, and platform constraints.

Choose one coherent direction. Do not mix unrelated styles, component shapes, shadows, and animation types just to make a screen appear “advanced.”

### Phase 5 — Build in small, reviewable increments

1. Establish tokens and layout primitives before styling every individual screen.
2. Build semantic page structure and the primary task path first.
3. Add reusable components only when behavior or visual rules genuinely repeat.
4. Implement all relevant component and page states, not just the default screenshot.
5. Add imagery, effects, and motion after hierarchy and content are stable.
6. Verify after each coherent step. Inspect the diff and the actual rendered UI.

### Phase 6 — Validate the experience

Run the validation protocol in Sections 13–16. Test real content, realistic viewport sizes, important states, keyboard access, accessible names, reduced motion, and the relevant browser/device. Fix issues that block comprehension or task completion before polishing minor details.

### Phase 7 — Hand off clearly

Summarize changed screens/components, user-visible behavior, design/architecture decisions, assumptions, tests and build commands run, and any unverified platform or browser. Mention known limitations without implying they were validated.

---

## 4. Professional UX experience pattern

### 4.1 Screen contract

Every meaningful page or screen should make these answers discoverable:

1. **Where am I?** Clear title, current navigation context, and recognizable structure.
2. **What can I do here?** Visible actions named by their outcome, with a clear relationship to the task.
3. **What information do I need?** Relevant explanations, content, options, and constraints placed before the decision they affect.
4. **What just happened?** Timely feedback for input, save, submit, navigation, or background activity.
5. **What if it fails or I change my mind?** Recovery, retry, correction, cancellation, undo, or a clear route to help when appropriate.

Do not force every page into the same number of cards or buttons. The contract is about comprehension and control, not a visual template.

### 4.2 Interaction loop

For every core task, design and implement:

1. **Orient:** Establish context, current location, and expected next step.
2. **Enable:** Present the right content and a recognizable action using the correct control.
3. **Respond:** Give immediate and accurate feedback; prevent duplicate or ambiguous submission where necessary.
4. **Recover:** Preserve work and explain how to fix an error, retry, cancel, or return.
5. **Complete:** Confirm what happened and offer the next useful step without inventing urgency.

### 4.3 Common interaction patterns

- **Navigation:** Use links for moving to another location, buttons for actions, and native semantics. Show the current location accessibly. A normal site navigation list is usually not an ARIA `menu` widget.
- **Forms:** Persistent associated labels; concise instructions before entry; clear required/format guidance; validation at a useful moment; field-level errors and an error summary for substantial forms; preserve values after error; announce important dynamic results accessibly.
- **Search:** Keep the query visible; distinguish suggestions from results; design no-results, loading, offline, and service-error states; let users revise the query easily.
- **Tabs:** Use when switching among related peer panels in the same context and implement the correct keyboard model. Use links/navigation when destinations should have their own URL or independent page identity.
- **Disclosure/accordion:** Use for optional supporting content. Do not hide information essential to a decision behind an ambiguous label.
- **Dialog/modal:** Reserve for a focused task or interruption. Label it, manage focus, close predictably, support keyboard operation, and restore focus to the trigger. Use a page or disclosure instead when the content is not truly modal.
- **Destructive or irreversible action:** Explain the consequence; make the destructive choice distinct; ask for confirmation when the consequence is significant; provide undo or recovery when feasible. Do not add confirmation dialogs to harmless actions that users can easily reverse.
- **Notifications/status:** Keep messages concise, actionable, and non-blocking unless immediate action is required. Do not use color or motion as the only signal.
- **Authentication:** Respect password managers and paste, label every field, give recoverable errors, avoid asking for information twice, and use the project’s approved secure authentication mechanisms.
- **Permissions:** Request at the moment the capability becomes useful, explain the purpose, request the minimum, and provide an understandable route if declined.

### 4.4 State matrix

Design only states that the product can actually reach, but never ignore a meaningful one. For each screen/component, ask:

| State | User should understand | Implementation expectation |
|---|---|---|
| Initial/default | What this view is and what can be done | Stable layout, visible labels, sensible focus and default selection |
| Loading/pending | The request was received and whether to wait | Avoid layout jumps; show progress if useful; guard against duplicate submits where appropriate |
| Empty/no results | Whether there is no data, no match, or no setup yet | Explain why and give the next useful action; do not show a blank panel |
| Validation/error | What failed, where, and how to recover | Plain-language message; preserve entered data; identify the affected field or operation |
| Offline/timeout | Whether the action was saved or needs retry | Distinguish unsent, pending, and completed work; avoid false success |
| Permission denied | What remains available and how to continue | Do not trap the user or repeatedly nag; offer settings/help only where appropriate |
| Success/complete | What changed and what happens next | Confirm the outcome; update content/state consistently |
| Disabled/unavailable | Why the action cannot be performed, if that is not obvious | Do not rely only on faded color; explain blockers and recovery where useful |

---

## 5. Visual direction: select deliberately

“Professional” does not mean every product should look like a generic SaaS dashboard, a black-and-purple gradient, or a luxury editorial site. Derive the visual direction from the audience, product promise, content, brand, context, and platform.

| Direction or treatment | Consider when | Guardrails / avoid when |
|---|---|---|
| **Editorial / publication** | Reading, expertise, narrative, or photography is central | Protect reading width, heading structure, image purpose, and mobile reading order; do not turn every section into a card |
| **Utility / productivity** | People perform repeated tasks or manage dense information | Use clear hierarchy, stable navigation, strong form/table behavior, and configurable density where needed; avoid decorative clutter |
| **Dashboard / overview** | Users need a high-level status view and clear paths into detail | Prioritize key measures and actions; use grids only for genuinely peer modules; provide units, time ranges, definitions, and no-data states |
| **Bento grid** | Several distinct modules deserve a compact overview or launchpad | Preserve semantic reading order and hierarchy at every breakpoint; vary card size only when importance/content warrants it; do not put every paragraph in a tile |
| **Minimal / calm** | Reducing competition improves comprehension or task focus | Keep necessary content, affordances, and contrast; minimalism is not empty space at the cost of discoverability |
| **Expressive / playful / brand-led** | Personality helps recognition, delight, or storytelling | Maintain task clarity, readable content, inclusive language, and mature states; illustration must not obscure the action |
| **Glass / translucent layers** | A purposeful floating control should retain some context from the changing content beneath it | Use sparingly; stable contrast and a solid fallback are mandatory; avoid text-heavy, form-heavy, or stacked glass surfaces |
| **Neumorphism / Soft UI** | A restrained soft surface treatment suits a simple, low-density, tested experience | Shadows alone are weak affordances; add real borders, fills, labels, state cues, and focus; do not use it as the primary language for action-critical UI |
| **Gradient, glow, or 3D** | It supports brand, depth, data, or product explanation | Keep content legible; use responsive fallbacks and test loading/rendering cost; do not add purely as “modern” decoration |
| **Dark theme** | User preference, environment, product context, or research supports it | Design it as a full theme with tested contrast, imagery, fields, boundaries, and states; do not simply invert colors or force it as the fashionable default |

A trend may be used only after it passes all five checks:

1. **Product fit:** Does it support the actual content or task?
2. **Comprehension:** Does hierarchy and interaction remain obvious?
3. **Inclusion:** Does it retain contrast, semantics, focus, and user-setting alternatives?
4. **Resilience:** Does the experience still work without the effect, image, animation, or preferred device?
5. **Evidence:** Has the treatment been reviewed with realistic content and, when the design is consequential, tested with representative users?

If it fails a check, simplify or remove the effect. Do not defend a style because it took effort to implement.

---

## 6. Layout and composition

### 6.1 Composition rules

- Establish one clear entry point for attention, then a second and third level. Scale, spacing, position, color, type weight, and alignment should reinforce—not compete with—the information hierarchy.
- Group related elements; separate unrelated groups. Use whitespace as structure, not as a substitute for content.
- Align repeated content to a consistent grid and spacing rhythm. Use a small tokenized spacing scale, then make exceptions only for a reason.
- Design from real content. Avoid fixed-height text containers, forced line breaks, clipped labels, and exact screenshot measurements when the content can vary.
- Keep page structure and DOM reading order logical. CSS must not create a confusing sequence for keyboard or screen-reader users.
- Use whitespace, rules, background tone, or typography before adding a border/card around every module.
- Choose sticky, fixed, floating, and full-screen elements conservatively. They must not cover content, focused controls, anchored headings, virtual keyboards, or platform safe areas.

### 6.2 Layout pattern selector

| Pattern | Good fit | Key checks |
|---|---|---|
| **Single-column content** | Reading, forms, setup, focused task flows | Comfortable line length; clear headings; primary action easy to find; no unnecessary sidebars |
| **Split layout** | A focused task beside supporting explanation, preview, or summary | Collapse in a useful order on narrow screens; do not shrink either side into unreadability |
| **Sidebar + content** | Repeat-use tools, admin, knowledge navigation, settings | Current location, collapsible behavior, keyboard/touch access, persistent context; do not make a sidebar the only route to an essential action |
| **Application shell** | Multi-route web app with persistent navigation and utility controls | Clear global vs. local navigation, page title, content region, mobile navigation adaptation, stable focus after route change |
| **Bento / card grid** | Overview of distinct status areas, launch points, or media | Meaningful grouping, consistent reading order, sensible stack on mobile, no decorative card explosion |
| **Editorial / asymmetric grid** | Storytelling, campaigns, portfolios, image-led content | Visual balance must not break reading order; control crops and text contrast; retain responsive meaning |
| **Data table / dense list** | Comparing values or scanning repeated records | Real table semantics for tabular data, labeled columns, row actions, clear sorting and empty states; on narrow screens preserve relationships via scroll or carefully designed alternate view |
| **Wizard / multi-step flow** | A task has true phases or needs staged collection | Explain progress, allow safe back/edit, preserve values, avoid unnecessary steps, expose validation and completion clearly |

### 6.3 Grid and responsive layout mechanics

- Use **CSS Grid** for two-dimensional page/module placement and **Flexbox** for one-dimensional alignment and distribution. They can be combined; do not force all layout into one technique.
- Prefer content-driven sizing (`minmax`, `min()`, `max()`, `clamp()`, wrapping, intrinsic sizes) over rigid pixel widths. Add breakpoints when the content or interaction no longer works—not because a device label says “tablet.”
- Container queries can help reusable components adapt to their available space; add them only when the component really needs independent adaptation and verify required browser support.
- Use a grid column count because the content supports it, not because a design trend says every screen needs twelve columns.
- Bento layouts are a **composition option**, not an information architecture. The most important task must not become visually smaller merely to make an irregular collage.
- Preserve table meaning on mobile. Horizontal scrolling may be better than hiding columns that users need to compare; if using a different compact presentation, preserve labels and equivalent information.
- Do not use CSS visual reordering to conceal a poor content order. Fix the source sequence.

---

## 7. Color, typography, brand, and content

### 7.1 Semantic color system

Define named roles rather than scattering raw color values through components. Example roles:

```text
canvas / surface / surface-raised
text-primary / text-secondary / text-inverse
border-subtle / border-strong / focus-ring
action-primary / action-secondary / action-danger
status-success / status-warning / status-error / status-info
```

Rules:

- Test each foreground/background combination in every supported theme and state. Normal text needs a WCAG 2.2 AA contrast ratio of at least **4.5:1**; large text needs **3:1**. Meaningful non-text UI components and graphics covered by the criterion generally need **3:1** against adjacent colors. Apply the standard’s definitions and exceptions; do not infer contrast from hue alone.
- Never communicate status, errors, selection, requiredness, or chart categories by color alone. Pair color with text, icon, shape, pattern, position, or a clear boundary.
- Provide visible focus and hover/pressed/selected/disabled states. Do not use low-contrast brand colors for essential text simply to match a brand sheet; tune the token while preserving brand character.
- Design themes semantically. Dark mode changes surfaces, elevation, borders, imagery, form controls, focus, chart colors, and shadows—not just page background and text.
- Use charts with readable labels and redundant encoding; verify color-vision differences and accessible text/table equivalents where the data matters.
- Use user preferences when appropriate and preserve user control. Support forced-colors/high-contrast behavior instead of overriding it.

WCAG 2.2 is the reference standard for web accessibility; a list of contrast ratios is not a complete accessibility audit. [W3C, WCAG 2.2](https://www.w3.org/TR/WCAG22/)

### 7.2 Typography

- Select fonts for legibility, language/script coverage, licensing, brand fit, available weights, and load cost. A variable font may simplify a family but is not automatically smaller or faster.
- Define semantic roles for display, page title, section headings, body, labels, helper text, and metadata. Pair appearance with actual semantic heading elements in logical order.
- Use flexible sizing and line-height; test large text, 200% zoom, user text-spacing overrides, and translated text. Do not truncate content that is needed to complete a task.
- Use a comfortable reading measure and rhythm. A rough desktop editorial starting point may be around 45–75 characters per line, but validate the actual font, language, device, and content.
- Avoid tiny low-contrast body copy, long all-caps passages, ultra-light text on images, and using color, italic, or font weight as the only cue.
- Do not insert visual line breaks into content unless they are intentional and resilient to localization.

### 7.3 Brand and UX writing

- Maintain recognizable tokens, tone, terminology, icon style, and interaction behavior across routes while allowing different tasks to use different layouts.
- Write specific headings, links, buttons, helper text, validation, confirmations, and errors. Prefer an action label that states the outcome (such as “Save changes”) over “Submit” or “Click here.”
- Tell users what happened and what they can do next. Avoid blame, vague jargon, fabricated urgency, and jokey errors in consequential flows.
- Use realistic content in the UI and tests. Do not ship “Lorem ipsum,” fake metrics, invented testimonials, or placeholder actions unless the user explicitly requested a prototype—and label prototype content clearly.
- Keep key information before the decision it affects. Plan for translation, pluralization, dates, currencies, and long names when relevant.

### 7.4 Imagery, icons, and assets

- Use images to identify, explain, or support the message. Do not make essential text or controls part of a raster image.
- Supply purpose-appropriate alt text: informative image = concise equivalent; functional image = action/destination; decorative image = empty alt; complex chart = nearby text/table or equivalent data description.
- Keep decorative icons out of the accessibility tree when adjacent text already communicates their meaning. Give icon-only controls a concise accessible name describing the action, not the icon’s appearance.
- Use responsive image candidates or art direction when appropriate; declare intrinsic dimensions to reserve space; lazy-load genuinely off-screen media, not the key above-the-fold/LCP image by default.
- Use licensed assets and follow repository rules. Do not create or imply authentic customer, team, or product photography when using generated or stock imagery.

---

## 8. Depth, materials, glass, and contemporary effects

### 8.1 Glassmorphism and platform Liquid Glass

Glassmorphism is a web visual treatment using a translucent fill, often `backdrop-filter` blur/saturation, a subtle edge/highlight, and layered depth. It exposes the content behind a surface, so contrast can change while the page scrolls or the underlying image/data changes.

Apple’s **Liquid Glass** is a distinct, platform-specific adaptive material for Apple UI. Apple’s guidance is useful for Apple-platform products, but a CSS blur/translucency effect is not a full implementation of that system material and should not be presented as equivalent. Do not apply platform styling indiscriminately to the web.

Use glass only when all of these are true:

1. A functional floating layer—such as restrained navigation chrome or a temporary contextual panel—benefits from maintaining a view of the content behind it.
2. The background beneath the glass is known or can be tested in its least favorable states.
3. Text, icons, component boundaries, and focus remain legible in all supported themes and responsive states.
4. There is a solid, contrast-tested fallback for browsers, devices, or settings where the effect is unavailable or reduced.
5. The effect does not create unacceptable motion, rendering cost, or visual competition.

Avoid glass as the default backing for long reading, dense tables, forms, error messages, critical decisions, or several stacked interface layers. Blur can soften a background but does not guarantee contrast. Avoid “glass on glass.”

Progressively enhance rather than making the effect a dependency:

```css
.glass-surface {
  /* Readable fallback is the baseline. */
  background: var(--surface-solid);
  color: var(--text-primary);
  border: 1px solid var(--border-strong);
}

@supports ((backdrop-filter: blur(1px)) or
           (-webkit-backdrop-filter: blur(1px))) {
  .glass-surface {
    /* Validate this token over every real backdrop. */
    background: var(--surface-glass-validated);
    -webkit-backdrop-filter: blur(0.75rem) saturate(1.2);
    backdrop-filter: blur(0.75rem) saturate(1.2);
  }
}

@media (prefers-reduced-transparency: reduce) {
  .glass-surface {
    background: var(--surface-solid);
    -webkit-backdrop-filter: none;
    backdrop-filter: none;
  }
}

@media (forced-colors: active) {
  .glass-surface {
    background: Canvas;
    color: CanvasText;
    border: 1px solid CanvasText;
    box-shadow: none;
    -webkit-backdrop-filter: none;
    backdrop-filter: none;
  }
}
```

`prefers-reduced-transparency` has limited browser availability; keep the solid fallback readable even when that preference cannot be detected. The CSS above is a pattern, not a guarantee: set actual tokens and re-test foreground/background contrast against photos, video, gradients, changing data, light/dark themes, and mobile layouts. Large or animated filters can affect rendering; profile on representative lower-power devices.

### 8.2 Neumorphism / Soft UI

Neumorphism uses a surface close to its background plus soft paired highlights/shadows to suggest raised or inset controls. Its characteristic subtle edges can make interactive and decorative surfaces difficult to distinguish. It is not inherently inaccessible, but the common shadow-only treatment is risky.

If a product uses it:

- Treat the shadow as decoration, never as the only boundary or interaction cue.
- Give controls real text contrast and distinguishable fill/border/accent; make labels visible.
- Specify default, hover, focus-visible, pressed, selected, and disabled states with more than a small shadow-direction change.
- Preserve native control roles/states; screen readers do not infer semantics from shadows.
- Use a visible focus ring that survives forced-colors mode and shadow removal.
- Prefer a limited secondary surface treatment or a simple, low-density widget; avoid a full low-contrast skin for dense dashboards, forms, checkout, and action-critical workflows.
- Confirm with task testing that users can identify what is interactive. If added borders and contrast remove the desired look, prioritize usability over the look.

### 8.3 Shadows, gradients, depth, and layering

Use shadow and elevation to communicate a consistent relationship, not as a substitute for borders, labels, or hierarchy. Define a small elevation system if the product needs one; do not assign a new dramatic shadow to each component. Gradients, glow, blur, texture, and 3D are optional brand/material tools; keep text contrast, loading cost, fallbacks, and user settings intact. Avoid stacking multiple decorative effects around every control.

---

## 9. Responsive, adaptive, and mobile experience

### 9.1 Responsive web and PWA

- Design for content and available space, not device marketing names. Use fluid containers, flexible grids, wrapping, and content-driven breakpoints.
- Start at the narrowest supported layout when that reveals content priority, then enhance for wider space. “Mobile-first” is a useful workflow, not a rule that every product must use the same sequence.
- Check narrow widths, touch/pointer use, landscape, large text, zoom, long strings, and real content. WCAG reflow should be considered at a width equivalent to **320 CSS pixels** for ordinary content, subject to the criterion’s exceptions.
- Ensure fixed headers, bottom bars, banners, toasts, and cookie UI do not obscure content, focus, or the on-screen keyboard. Account for browser chrome and safe-area insets where relevant.
- Keep essential controls reachable and tap targets generous. WCAG 2.2 AA’s minimum target-size criterion is generally **24 × 24 CSS pixels**, subject to defined exceptions; touch-first interfaces should normally provide more comfortable targets and spacing. Apply current platform guidance for native apps rather than copying web pixels into dp/pt.
- Preserve entered work if navigation, network, or orientation changes. For an offline feature, communicate what is cached, pending, and synchronized; do not imply a server action succeeded while offline.
- A PWA is an optional delivery model. Add installation and offline support only when they provide user value and the update, cache, and privacy behavior is designed.

### 9.2 Native and cross-platform mobile

A mobile app is not simply a narrow website. Before implementation, confirm whether the request means responsive web, installable PWA, a native iOS/Android app, or a cross-platform app. If unclear and it materially affects delivery, ask.

For native/cross-platform work:

- Use the platform’s accessibility APIs, native semantics, navigation/back behavior, safe areas, text scaling, keyboard/input handling, and permission conventions. Check current official platform guidance for exact patterns and sizes.
- Adapt the interaction to touch and reach. Do not make hover, tiny hit regions, or a precise drag the only path to an essential task.
- Treat gestures as shortcuts, not the only affordance. Provide visible alternatives and announce state changes accessibly.
- Test with VoiceOver/TalkBack or relevant platform screen readers, switch/keyboard access where applicable, large text, orientation changes, and real device sizes.
- Request camera, location, notifications, contacts, or other permissions only when needed; explain the benefit; request the least access; support denial without trapping the user.
- Make the on-screen keyboard, system bars, interruptions, resume/background, network loss, and back navigation part of the task flow.
- Share tokens, content models, and business logic only where it reduces duplication. Keep platform-specific interaction patterns when they better meet user expectations.

---

## 10. Interaction, transitions, and animation

Motion is a communication tool, not a requirement for polish. Static content can have useful interaction feedback; dynamic applications do not need every update to animate.

### 10.1 Choose motion by purpose

| Motion purpose | Useful when | Avoid |
|---|---|---|
| **Input feedback** | A quick response confirms a toggle, selection, or completed action | An effect that delays input or communicates state only through motion |
| **Spatial continuity** | A short transition helps people understand where a panel or item went | Long or complex transitions between unrelated screens |
| **Progress/wait** | The work takes enough time that progress or status reduces uncertainty | Endless spinner with no message, fake progress, or blocking animation for a fast action |
| **Data change** | A restrained cue helps locate a significant updated value | Animating an entire dashboard on every polling update or flashing values repeatedly |
| **Story/brand** | A restrained, optional animation supports a narrative or identity | Autoplaying motion that competes with reading, triggers discomfort, or hides content |

### 10.2 Static websites

For primarily informational/static pages, prefer fast content rendering and optional, brief effects. Hover/focus/pressed feedback may be useful, but motion should not be required to reveal essential content. Avoid scroll-triggered animation that causes hidden text, layout shifts, reading delays, or repeated movement. Avoid autoplaying background video; if media is important, provide controls and a static/poster fallback. Static pages still need functional focus, menu, disclosure, form, and error states.

### 10.3 Dynamic sites and applications

Use transitions when they make a state change easier to perceive: submitting, expanding a panel, selecting a tab, opening a dialog, or moving between related views. Keep feedback immediate and short enough not to slow the task. Preserve stable layout while data loads. For live updates, indicate what changed without moving focus or repeatedly interrupting a screen reader. Use optimistic updates only when rollback/error behavior is clear.

### 10.4 Engineering and accessibility rules

- Animate `transform` and `opacity` when suitable; avoid frequent layout-changing animation and expensive large blur/filter effects. Profile rather than assuming an animation is cheap.
- Keep motion optional and honor `prefers-reduced-motion`. Provide a reduced or still alternative for meaningful motion, not just a smaller version of the same discomfort.
- Use text/icon/state changes in addition to motion. Do not flash or pulse essential information indefinitely.
- Avoid autoplay, parallax, and looping decorative motion by default. If the user can pause/stop motion when required, provide a discoverable control.
- Prefer native/CSS transitions for simple UI changes; add an animation library only when complexity, sequencing, gestures, or maintainability justify it.
- Do not set `outline: none` to make an animation look clean. Focus must remain visible.

Example reduced-motion handling for optional effects:

```css
.panel-enter {
  transition: opacity 160ms ease, transform 160ms ease;
}

@media (prefers-reduced-motion: reduce) {
  html {
    scroll-behavior: auto;
  }

  .panel-enter,
  .decorative-motion {
    animation: none;
    transition: none;
    transform: none;
  }
}
```

Use effect-specific classes rather than blindly disabling every transition in a whole application; keep state feedback understandable without animation.

---

## 11. Accessibility and inclusive implementation

Treat **WCAG 2.2 AA as a practical web baseline** unless the product/jurisdiction requires more. Verify all applicable success criteria before making a conformance claim. For native applications, follow the platform accessibility APIs and validate with actual platform assistive technology.

### 11.1 Semantic structure and names

- Use native HTML elements first: headings, landmarks, lists, buttons, anchors, form controls, tables, and dialogs when appropriate.
- Use a `<button>` for an action and an `<a>` for navigation. Do not make a clickable `<div>` or `<span>` without a compelling reason and complete equivalent keyboard/semantic behavior.
- Give each control a persistent accessible name. Placeholder text is not a label. Icon-only controls need an action name; decorative icons should not create duplicate announcements.
- Keep headings meaningful and nested logically; provide one clear page-level heading in a normal page unless product architecture has a reason otherwise. Use landmarks to support navigation.
- Prefer native semantics over ARIA. Add ARIA only when native HTML cannot express the required role, state, or relationship; implement the corresponding keyboard interaction.

### 11.2 Operation and state

- Complete every essential task with a keyboard or supported alternative input. Check tab order, activation keys, escape/cancel, focus restoration, and no keyboard trap.
- Make focus visible, sufficiently distinct, and not completely obscured by sticky elements, dialogs, or banners.
- Ensure hover-only information also appears on focus/touch or through a visible control.
- Expose selected, expanded, checked, pressed, current, busy, and invalid states programmatically and visually.
- Provide accessible status announcements for meaningful asynchronous changes without repeatedly interrupting people. Preserve logical focus after navigation and dialog close.
- Use error text and instructions in addition to color. Identify the affected field and how to correct it; preserve entered data where possible.

### 11.3 Perception and adaptation

- Verify the contrast values in Section 7 in rendered states, themes, and overlay compositions.
- Test reflow, zoom, increased text size and spacing, orientation, high contrast/forced colors, reduced motion, and reduced transparency where the platform/browser supports them.
- Respect user preferences and do not override system colors or motion settings for visual consistency.
- Ensure images, charts, video, audio, and animation have suitable alternatives, captions, descriptions, controls, or equivalent information where needed.
- Avoid relying only on location, shape, sound, motion, color, or gesture to convey meaning.

### 11.4 Validation discipline

Combine automated checks with manual review. Automated tools can identify some missing names, contrast problems, and structural issues; they cannot prove that the task is understandable, keyboard behavior is correct, or a screen-reader user can complete a real workflow. Test important journeys with keyboard and relevant assistive technology; include people with disabilities in user research when the task warrants it.

---

## 12. Frontend code and component standards

### 12.1 Repository and architecture

- Follow the installed framework, component model, routing, data-fetching, state, styling, and test conventions. Check package scripts rather than guessing commands.
- Keep changes focused. Do not rewrite a project, replace its design system, or switch frameworks just to satisfy a visual request.
- Separate semantic structure, styling, and behavior in the idiomatic way for the chosen stack. Keep components cohesive and their public props/state understandable.
- Extract a shared component when behavior, semantics, or visual rules truly repeat. Avoid both giant page components and one-component-per-wrapper overengineering.
- Use design tokens for repeated roles and support themes through semantic variables. Avoid brittle selectors and duplicate one-off values.
- Keep server/data state distinct from local UI state where the framework requires it; avoid duplicated sources of truth, stale derived state, and unnecessary global state.

### 12.2 Components and interactions

Every interactive component must define:

- Purpose and semantic element/role.
- Accessible name, value, and relationships.
- Default, hover where applicable, focus-visible, pressed, selected, disabled, busy, error, and expanded/collapsed states as relevant.
- Keyboard/touch operation and focus behavior.
- Responsive behavior and content overflow.
- Reduced-motion/high-contrast behavior if it uses effects.
- Empty/loading/error response if it depends on data.

Prefer native form controls and browser behavior when they satisfy the requirements. Custom menus, comboboxes, grids, and date pickers are high-risk: use a well-maintained accessible implementation or native control unless custom behavior is essential and can be fully tested.

### 12.3 Data and failure behavior

- Handle loading, empty, success, error, retry, and cancellation explicitly for asynchronous content.
- Prevent stale requests from overwriting newer results where relevant. Do not show a success state before the source of truth confirms it unless optimistic behavior has an explicit rollback path.
- Validate inputs on the client for usability and on the trusted server for security/business rules. Client validation is not a security boundary.
- Preserve meaningful user input on recoverable failures. Avoid destructive resets after a failed save.
- Do not hide important errors in console logs or silently swallow exceptions.

### 12.4 Privacy and frontend security

- Never put API secrets, private credentials, privileged service keys, or authorization decisions solely in client code.
- Treat URL parameters, user input, API responses, and uploaded content as untrusted. Escape/render safely; avoid unsafe HTML injection and unsafe URL schemes.
- Do not log passwords, tokens, personal information, form contents, or sensitive identifiers. Collect only necessary analytics and follow consent/privacy requirements.
- Use the project’s approved auth and API paths. Do not hardcode a production endpoint or call browser `localhost` as a deployment integration strategy; use environment-aware configuration and appropriate same-origin/proxy design.
- Review third-party scripts, fonts, analytics, maps, and embeds for privacy, reliability, cost, license, performance, and fallback implications.

---

## 13. Performance, resilience, and discoverability

### 13.1 Web performance

Use field data as well as local/lab testing. Current Core Web Vitals “good” targets are **LCP ≤ 2.5 seconds, INP ≤ 200 milliseconds, and CLS ≤ 0.1 at the 75th percentile**. These are useful indicators, not a complete UX score or a guarantee that a product is fast for every user. Segment by mobile/desktop and real usage where possible. [web.dev, Web Vitals](https://web.dev/articles/vitals)

- Reserve image/media dimensions to prevent layout shifts; provide responsive source sizes where useful.
- Optimize the primary content and LCP asset; do not lazy-load the main above-the-fold image by default. Lazy-load genuinely off-screen media.
- Avoid shipping large client bundles or hydrating static content without a reason. Split code at useful routes/features, not into many costly requests by habit.
- Reduce unnecessary re-rendering, synchronous work, large DOM trees, oversized fonts, and unneeded third-party scripts.
- Use real loading feedback and preserve layout stability. Respect slow networks and low-power devices.
- Evaluate blur, backdrop filters, large shadows, video, canvas, 3D, and animation on representative hardware. A build-time asset preview does not prove runtime performance.

### 13.2 SEO and linkability

For public/indexable web content, use meaningful document titles, metadata, semantic headings, crawlable links, stable URLs, canonical behavior when needed, and accurate structured data only where the content qualifies. Make core content available to the chosen rendering strategy; do not rely on decorative client-only content for essential information. Authenticated/private applications should not expose private routes or data to indexing.

### 13.3 Resilience

- Keep essential content and controls understandable if a non-essential asset or effect fails.
- Design for missing images, slow APIs, timeouts, empty data, offline conditions where relevant, and invalid server responses.
- Give users accurate status. Do not claim work was saved, paid, submitted, or deleted without confirmation from the responsible system.
- Use retry only when useful and safe; make retries bounded and avoid duplicate transactions.

---

## 14. Quality assurance and test protocol

Match testing depth to risk. For any visible frontend change, inspect the actual rendered page—not just source code or a static design file.

### 14.1 Functional checks

- Test each acceptance criterion through the real interaction.
- Test primary and alternate flows, validation, cancellation, retry, back navigation, empty/error/success states, and persistence where relevant.
- Confirm links go to the right route, controls perform the named action, and route changes leave focus/context understandable.
- Exercise long content, large values, no data, duplicate actions, slow responses, and network loss for data-driven screens.

### 14.2 Responsive and visual checks

Inspect at least one narrow phone width, a typical phone, a tablet/intermediate width, a laptop, and a wide layout where supported. Include portrait/landscape where relevant, 200% zoom, larger text, long/localized strings, and WCAG reflow conditions. Use target project devices rather than treating the list as a set of universal breakpoints.

Check:

- No horizontal overflow or hidden essential content.
- Grid collapse and reading order remain intentional.
- Sticky/fixed UI does not cover focus, content, or virtual keyboard.
- Text wraps; buttons, tables, charts, images, dialogs, and forms remain usable.
- Visual hierarchy, contrast, icon alignment, image crop, whitespace, and states are coherent.
- No missing fonts/assets, layout shift, placeholder copy, or accidental browser-console errors.

A screenshot/visual regression can catch rendering differences but does not establish task success or accessibility.

### 14.3 Accessibility checks

- Run an available automated accessibility scan; investigate every issue rather than blindly accepting the score.
- Navigate the main task using keyboard only. Verify logical order, visible focus, no trap, and correct activation.
- Check semantics, accessible names, labels, headings, live updates, errors, and dialog focus.
- Test contrast for important text, controls, component boundaries, states, and images/overlays.
- Test reduced motion, high contrast/forced colors, zoom/large text, and reduced transparency where supported.
- Test with a relevant screen reader/browser or platform assistive technology for important user journeys.

### 14.4 Build and static checks

Use project-defined commands for linting, formatting, type-checking, unit/component tests, integration/e2e tests, accessibility checks, and production build as appropriate. Fix issues introduced by the change. Report environment or pre-existing failures separately. Never delete or weaken a test just to obtain a passing run without understanding and justifying the change.

### 14.5 Manual test matrix template

| Dimension | Test cases |
|---|---|
| Viewport | Narrow, typical mobile, tablet/intermediate, desktop, wide; relevant orientations |
| Input | Keyboard, pointer, touch, switch/assistive input where applicable |
| Preferences | Reduced motion, reduced transparency, increased contrast/forced colors, dark/light theme |
| Content | Short/long strings, translation, empty, large dataset, image failure, unusual but valid values |
| Network | Normal, slow, offline, timeout, retry, stale response |
| UI states | Default, hover, focus, pressed, selected, disabled, loading, error, success, empty |
| Platform | Supported browser matrix, native OS/device matrix, safe areas and virtual keyboard |

---

## 15. Design decision record

For a non-trivial design or architecture choice, record a brief note:

```text
Decision:
User/task reason:
Alternatives considered:
Accessibility/responsive/performance impact:
Assumptions or limitations:
How it will be validated:
```

Use this for choices such as framework/rendering mode, navigation, a custom widget, glass effects, animation libraries, charting, or a new dependency. Do not document every tiny CSS adjustment.

---

## 16. Anti-patterns: do not ship these

- A generic template dressed in gradients that ignores the actual brand, content, and user task.
- A beautiful hero with no clear purpose, misleading CTA, or route to the product’s actual value.
- Cards for every paragraph or a bento collage where reading order and hierarchy are unclear.
- Glass or low-contrast neumorphism on task-critical controls without a tested contrast/boundary strategy.
- Body text on changing backgrounds, glass stacked on glass, or blur used as a substitute for readable contrast.
- Hover-only menus or controls, icon-only actions with no accessible name, clickable non-semantic elements, or invisible keyboard focus.
- Fake buttons, dead links, TODO text, lorem ipsum, empty routes, or placeholder interactions presented as finished work.
- Forms with placeholder-only labels, vague “Something went wrong” errors, lost input after failure, or validation that blames the user.
- Infinite motion, autoplay, parallax, animated metric churn, or scroll reveals that hide/delay content without a user benefit.
- A layout that works only at one screenshot size, uses clipped text, relies on fixed heights, or breaks at zoom/localization.
- Accessibility claims based only on a plugin score; visual tests used as a substitute for interaction tests.
- New dependencies, framework rewrites, or extensive abstractions with no concrete value.
- Exposing sensitive data or secrets in client code, URLs, logs, analytics, or public assets.
- Any final report that says a test, device, or accessibility check passed when it was not run.

---

## 17. Final handoff checklist

Before finishing, confirm:

### Experience
- [ ] The primary audience and task are clear; page/screen purpose is understandable.
- [ ] Navigation, labels, primary actions, feedback, and recovery paths make sense.
- [ ] Realistic loading, empty, error, success, and offline states are implemented where applicable.
- [ ] The visual style supports the product and does not overpower it.

### Design and responsive behavior
- [ ] Composition, hierarchy, alignment, spacing, type, imagery, and surfaces are coherent.
- [ ] Narrow and wide layouts, content length, zoom, and relevant orientation are checked.
- [ ] Trend treatments (glass, bento, neumorphism, motion, 3D, dark mode) are optional, justified, and have suitable fallbacks.

### Accessibility and engineering
- [ ] Semantic elements and accessible names/states are correct.
- [ ] Keyboard, focus, contrast, motion, high contrast, and assistive technology were checked to the level appropriate for the task.
- [ ] No secrets, unsafe content injection, unnecessary telemetry, or avoidable performance regressions were introduced.
- [ ] Relevant lint/type/test/build commands were run and their results are reported accurately.

### Delivery
- [ ] Final diff is focused; no unrelated or temporary files remain.
- [ ] User-facing assumptions, limitations, and unverified behavior are stated.
- [ ] The handoff says what changed, where it changed, and how it was validated.

---

## 18. Source of truth and further guidance

Use this skill with the project’s own instructions and authoritative platform documentation. For version-sensitive behavior, verify the current official source instead of trusting a trend post or memory.

- `UI_UX_FRONTEND_DESIGN_RESEARCH.md` — companion research and the source for UX, visual-design, accessibility, trend, and workflow recommendations in this skill.
- `DEVELOPMENT_SKILL.md` — general software-agent protocol for repository inspection, implementation, testing, security, and handoff.
- [W3C — WCAG 2.2](https://www.w3.org/TR/WCAG22/) — web accessibility success criteria.
- [W3C WAI — ARIA Authoring Practices Guide](https://www.w3.org/WAI/ARIA/apg/) — interaction patterns when native HTML is insufficient.
- [MDN — CSS media queries for accessibility preferences](https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Media_queries/Using_for_accessibility) — browser preference queries; verify support and provide robust fallbacks.
- [MDN — `backdrop-filter`](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/backdrop-filter) — browser behavior for web glass effects.
- [Apple Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/) — current Apple-platform design guidance.
- [Material Design 3](https://m3.material.io/) — Android/Material design guidance; apply it when appropriate, not as a universal web standard.
- [web.dev — Web Vitals](https://web.dev/articles/vitals) — web performance field metrics and thresholds.

**Final rule:** Build the experience that best serves this product’s users. Use modern techniques as tools, not as proof of modernity.
