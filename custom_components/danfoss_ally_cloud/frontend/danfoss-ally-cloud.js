/**
 * @license
 * Copyright 2019 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const t$3 = globalThis, e$2 = t$3.ShadowRoot && (void 0 === t$3.ShadyCSS || t$3.ShadyCSS.nativeShadow) && "adoptedStyleSheets" in Document.prototype && "replace" in CSSStyleSheet.prototype, s$2 = Symbol(), o$4 = /* @__PURE__ */ new WeakMap();
let n$3 = class n {
  constructor(t2, e2, o2) {
    if (this._$cssResult$ = true, o2 !== s$2) throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");
    this.cssText = t2, this.t = e2;
  }
  get styleSheet() {
    let t2 = this.o;
    const s2 = this.t;
    if (e$2 && void 0 === t2) {
      const e2 = void 0 !== s2 && 1 === s2.length;
      e2 && (t2 = o$4.get(s2)), void 0 === t2 && ((this.o = t2 = new CSSStyleSheet()).replaceSync(this.cssText), e2 && o$4.set(s2, t2));
    }
    return t2;
  }
  toString() {
    return this.cssText;
  }
};
const r$4 = (t2) => new n$3("string" == typeof t2 ? t2 : t2 + "", void 0, s$2), i$3 = (t2, ...e2) => {
  const o2 = 1 === t2.length ? t2[0] : e2.reduce((e3, s2, o3) => e3 + ((t3) => {
    if (true === t3._$cssResult$) return t3.cssText;
    if ("number" == typeof t3) return t3;
    throw Error("Value passed to 'css' function must be a 'css' function result: " + t3 + ". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.");
  })(s2) + t2[o3 + 1], t2[0]);
  return new n$3(o2, t2, s$2);
}, S$1 = (s2, o2) => {
  if (e$2) s2.adoptedStyleSheets = o2.map((t2) => t2 instanceof CSSStyleSheet ? t2 : t2.styleSheet);
  else for (const e2 of o2) {
    const o3 = document.createElement("style"), n3 = t$3.litNonce;
    void 0 !== n3 && o3.setAttribute("nonce", n3), o3.textContent = e2.cssText, s2.appendChild(o3);
  }
}, c$2 = e$2 ? (t2) => t2 : (t2) => t2 instanceof CSSStyleSheet ? ((t3) => {
  let e2 = "";
  for (const s2 of t3.cssRules) e2 += s2.cssText;
  return r$4(e2);
})(t2) : t2;
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const { is: i$2, defineProperty: e$1, getOwnPropertyDescriptor: h$1, getOwnPropertyNames: r$3, getOwnPropertySymbols: o$3, getPrototypeOf: n$2 } = Object, a$1 = globalThis, c$1 = a$1.trustedTypes, l$1 = c$1 ? c$1.emptyScript : "", p$1 = a$1.reactiveElementPolyfillSupport, d$1 = (t2, s2) => t2, u$1 = { toAttribute(t2, s2) {
  switch (s2) {
    case Boolean:
      t2 = t2 ? l$1 : null;
      break;
    case Object:
    case Array:
      t2 = null == t2 ? t2 : JSON.stringify(t2);
  }
  return t2;
}, fromAttribute(t2, s2) {
  let i2 = t2;
  switch (s2) {
    case Boolean:
      i2 = null !== t2;
      break;
    case Number:
      i2 = null === t2 ? null : Number(t2);
      break;
    case Object:
    case Array:
      try {
        i2 = JSON.parse(t2);
      } catch (t3) {
        i2 = null;
      }
  }
  return i2;
} }, f$1 = (t2, s2) => !i$2(t2, s2), b$1 = { attribute: true, type: String, converter: u$1, reflect: false, useDefault: false, hasChanged: f$1 };
Symbol.metadata ??= Symbol("metadata"), a$1.litPropertyMetadata ??= /* @__PURE__ */ new WeakMap();
let y$1 = class y extends HTMLElement {
  static addInitializer(t2) {
    this._$Ei(), (this.l ??= []).push(t2);
  }
  static get observedAttributes() {
    return this.finalize(), this._$Eh && [...this._$Eh.keys()];
  }
  static createProperty(t2, s2 = b$1) {
    if (s2.state && (s2.attribute = false), this._$Ei(), this.prototype.hasOwnProperty(t2) && ((s2 = Object.create(s2)).wrapped = true), this.elementProperties.set(t2, s2), !s2.noAccessor) {
      const i2 = Symbol(), h2 = this.getPropertyDescriptor(t2, i2, s2);
      void 0 !== h2 && e$1(this.prototype, t2, h2);
    }
  }
  static getPropertyDescriptor(t2, s2, i2) {
    const { get: e2, set: r2 } = h$1(this.prototype, t2) ?? { get() {
      return this[s2];
    }, set(t3) {
      this[s2] = t3;
    } };
    return { get: e2, set(s3) {
      const h2 = e2?.call(this);
      r2?.call(this, s3), this.requestUpdate(t2, h2, i2);
    }, configurable: true, enumerable: true };
  }
  static getPropertyOptions(t2) {
    return this.elementProperties.get(t2) ?? b$1;
  }
  static _$Ei() {
    if (this.hasOwnProperty(d$1("elementProperties"))) return;
    const t2 = n$2(this);
    t2.finalize(), void 0 !== t2.l && (this.l = [...t2.l]), this.elementProperties = new Map(t2.elementProperties);
  }
  static finalize() {
    if (this.hasOwnProperty(d$1("finalized"))) return;
    if (this.finalized = true, this._$Ei(), this.hasOwnProperty(d$1("properties"))) {
      const t3 = this.properties, s2 = [...r$3(t3), ...o$3(t3)];
      for (const i2 of s2) this.createProperty(i2, t3[i2]);
    }
    const t2 = this[Symbol.metadata];
    if (null !== t2) {
      const s2 = litPropertyMetadata.get(t2);
      if (void 0 !== s2) for (const [t3, i2] of s2) this.elementProperties.set(t3, i2);
    }
    this._$Eh = /* @__PURE__ */ new Map();
    for (const [t3, s2] of this.elementProperties) {
      const i2 = this._$Eu(t3, s2);
      void 0 !== i2 && this._$Eh.set(i2, t3);
    }
    this.elementStyles = this.finalizeStyles(this.styles);
  }
  static finalizeStyles(s2) {
    const i2 = [];
    if (Array.isArray(s2)) {
      const e2 = new Set(s2.flat(1 / 0).reverse());
      for (const s3 of e2) i2.unshift(c$2(s3));
    } else void 0 !== s2 && i2.push(c$2(s2));
    return i2;
  }
  static _$Eu(t2, s2) {
    const i2 = s2.attribute;
    return false === i2 ? void 0 : "string" == typeof i2 ? i2 : "string" == typeof t2 ? t2.toLowerCase() : void 0;
  }
  constructor() {
    super(), this._$Ep = void 0, this.isUpdatePending = false, this.hasUpdated = false, this._$Em = null, this._$Ev();
  }
  _$Ev() {
    this._$ES = new Promise((t2) => this.enableUpdating = t2), this._$AL = /* @__PURE__ */ new Map(), this._$E_(), this.requestUpdate(), this.constructor.l?.forEach((t2) => t2(this));
  }
  addController(t2) {
    (this._$EO ??= /* @__PURE__ */ new Set()).add(t2), void 0 !== this.renderRoot && this.isConnected && t2.hostConnected?.();
  }
  removeController(t2) {
    this._$EO?.delete(t2);
  }
  _$E_() {
    const t2 = /* @__PURE__ */ new Map(), s2 = this.constructor.elementProperties;
    for (const i2 of s2.keys()) this.hasOwnProperty(i2) && (t2.set(i2, this[i2]), delete this[i2]);
    t2.size > 0 && (this._$Ep = t2);
  }
  createRenderRoot() {
    const t2 = this.shadowRoot ?? this.attachShadow(this.constructor.shadowRootOptions);
    return S$1(t2, this.constructor.elementStyles), t2;
  }
  connectedCallback() {
    this.renderRoot ??= this.createRenderRoot(), this.enableUpdating(true), this._$EO?.forEach((t2) => t2.hostConnected?.());
  }
  enableUpdating(t2) {
  }
  disconnectedCallback() {
    this._$EO?.forEach((t2) => t2.hostDisconnected?.());
  }
  attributeChangedCallback(t2, s2, i2) {
    this._$AK(t2, i2);
  }
  _$ET(t2, s2) {
    const i2 = this.constructor.elementProperties.get(t2), e2 = this.constructor._$Eu(t2, i2);
    if (void 0 !== e2 && true === i2.reflect) {
      const h2 = (void 0 !== i2.converter?.toAttribute ? i2.converter : u$1).toAttribute(s2, i2.type);
      this._$Em = t2, null == h2 ? this.removeAttribute(e2) : this.setAttribute(e2, h2), this._$Em = null;
    }
  }
  _$AK(t2, s2) {
    const i2 = this.constructor, e2 = i2._$Eh.get(t2);
    if (void 0 !== e2 && this._$Em !== e2) {
      const t3 = i2.getPropertyOptions(e2), h2 = "function" == typeof t3.converter ? { fromAttribute: t3.converter } : void 0 !== t3.converter?.fromAttribute ? t3.converter : u$1;
      this._$Em = e2;
      const r2 = h2.fromAttribute(s2, t3.type);
      this[e2] = r2 ?? this._$Ej?.get(e2) ?? r2, this._$Em = null;
    }
  }
  requestUpdate(t2, s2, i2, e2 = false, h2) {
    if (void 0 !== t2) {
      const r2 = this.constructor;
      if (false === e2 && (h2 = this[t2]), i2 ??= r2.getPropertyOptions(t2), !((i2.hasChanged ?? f$1)(h2, s2) || i2.useDefault && i2.reflect && h2 === this._$Ej?.get(t2) && !this.hasAttribute(r2._$Eu(t2, i2)))) return;
      this.C(t2, s2, i2);
    }
    false === this.isUpdatePending && (this._$ES = this._$EP());
  }
  C(t2, s2, { useDefault: i2, reflect: e2, wrapped: h2 }, r2) {
    i2 && !(this._$Ej ??= /* @__PURE__ */ new Map()).has(t2) && (this._$Ej.set(t2, r2 ?? s2 ?? this[t2]), true !== h2 || void 0 !== r2) || (this._$AL.has(t2) || (this.hasUpdated || i2 || (s2 = void 0), this._$AL.set(t2, s2)), true === e2 && this._$Em !== t2 && (this._$Eq ??= /* @__PURE__ */ new Set()).add(t2));
  }
  async _$EP() {
    this.isUpdatePending = true;
    try {
      await this._$ES;
    } catch (t3) {
      Promise.reject(t3);
    }
    const t2 = this.scheduleUpdate();
    return null != t2 && await t2, !this.isUpdatePending;
  }
  scheduleUpdate() {
    return this.performUpdate();
  }
  performUpdate() {
    if (!this.isUpdatePending) return;
    if (!this.hasUpdated) {
      if (this.renderRoot ??= this.createRenderRoot(), this._$Ep) {
        for (const [t4, s3] of this._$Ep) this[t4] = s3;
        this._$Ep = void 0;
      }
      const t3 = this.constructor.elementProperties;
      if (t3.size > 0) for (const [s3, i2] of t3) {
        const { wrapped: t4 } = i2, e2 = this[s3];
        true !== t4 || this._$AL.has(s3) || void 0 === e2 || this.C(s3, void 0, i2, e2);
      }
    }
    let t2 = false;
    const s2 = this._$AL;
    try {
      t2 = this.shouldUpdate(s2), t2 ? (this.willUpdate(s2), this._$EO?.forEach((t3) => t3.hostUpdate?.()), this.update(s2)) : this._$EM();
    } catch (s3) {
      throw t2 = false, this._$EM(), s3;
    }
    t2 && this._$AE(s2);
  }
  willUpdate(t2) {
  }
  _$AE(t2) {
    this._$EO?.forEach((t3) => t3.hostUpdated?.()), this.hasUpdated || (this.hasUpdated = true, this.firstUpdated(t2)), this.updated(t2);
  }
  _$EM() {
    this._$AL = /* @__PURE__ */ new Map(), this.isUpdatePending = false;
  }
  get updateComplete() {
    return this.getUpdateComplete();
  }
  getUpdateComplete() {
    return this._$ES;
  }
  shouldUpdate(t2) {
    return true;
  }
  update(t2) {
    this._$Eq &&= this._$Eq.forEach((t3) => this._$ET(t3, this[t3])), this._$EM();
  }
  updated(t2) {
  }
  firstUpdated(t2) {
  }
};
y$1.elementStyles = [], y$1.shadowRootOptions = { mode: "open" }, y$1[d$1("elementProperties")] = /* @__PURE__ */ new Map(), y$1[d$1("finalized")] = /* @__PURE__ */ new Map(), p$1?.({ ReactiveElement: y$1 }), (a$1.reactiveElementVersions ??= []).push("2.1.2");
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const t$2 = globalThis, i$1 = (t2) => t2, s$1 = t$2.trustedTypes, e = s$1 ? s$1.createPolicy("lit-html", { createHTML: (t2) => t2 }) : void 0, h = "$lit$", o$2 = `lit$${Math.random().toFixed(9).slice(2)}$`, n$1 = "?" + o$2, r$2 = `<${n$1}>`, l = document, c = () => l.createComment(""), a = (t2) => null === t2 || "object" != typeof t2 && "function" != typeof t2, u = Array.isArray, d = (t2) => u(t2) || "function" == typeof t2?.[Symbol.iterator], f = "[ 	\n\f\r]", v = /<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g, _ = /-->/g, m = />/g, p = RegExp(`>|${f}(?:([^\\s"'>=/]+)(${f}*=${f}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`, "g"), g = /'/g, $ = /"/g, y2 = /^(?:script|style|textarea|title)$/i, x = (t2) => (i2, ...s2) => ({ _$litType$: t2, strings: i2, values: s2 }), b = x(1), w = x(2), E = Symbol.for("lit-noChange"), A = Symbol.for("lit-nothing"), C = /* @__PURE__ */ new WeakMap(), P = l.createTreeWalker(l, 129);
function V(t2, i2) {
  if (!u(t2) || !t2.hasOwnProperty("raw")) throw Error("invalid template strings array");
  return void 0 !== e ? e.createHTML(i2) : i2;
}
const N = (t2, i2) => {
  const s2 = t2.length - 1, e2 = [];
  let n3, l2 = 2 === i2 ? "<svg>" : 3 === i2 ? "<math>" : "", c2 = v;
  for (let i3 = 0; i3 < s2; i3++) {
    const s3 = t2[i3];
    let a2, u2, d2 = -1, f2 = 0;
    for (; f2 < s3.length && (c2.lastIndex = f2, u2 = c2.exec(s3), null !== u2); ) f2 = c2.lastIndex, c2 === v ? "!--" === u2[1] ? c2 = _ : void 0 !== u2[1] ? c2 = m : void 0 !== u2[2] ? (y2.test(u2[2]) && (n3 = RegExp("</" + u2[2], "g")), c2 = p) : void 0 !== u2[3] && (c2 = p) : c2 === p ? ">" === u2[0] ? (c2 = n3 ?? v, d2 = -1) : void 0 === u2[1] ? d2 = -2 : (d2 = c2.lastIndex - u2[2].length, a2 = u2[1], c2 = void 0 === u2[3] ? p : '"' === u2[3] ? $ : g) : c2 === $ || c2 === g ? c2 = p : c2 === _ || c2 === m ? c2 = v : (c2 = p, n3 = void 0);
    const x2 = c2 === p && t2[i3 + 1].startsWith("/>") ? " " : "";
    l2 += c2 === v ? s3 + r$2 : d2 >= 0 ? (e2.push(a2), s3.slice(0, d2) + h + s3.slice(d2) + o$2 + x2) : s3 + o$2 + (-2 === d2 ? i3 : x2);
  }
  return [V(t2, l2 + (t2[s2] || "<?>") + (2 === i2 ? "</svg>" : 3 === i2 ? "</math>" : "")), e2];
};
class S {
  constructor({ strings: t2, _$litType$: i2 }, e2) {
    let r2;
    this.parts = [];
    let l2 = 0, a2 = 0;
    const u2 = t2.length - 1, d2 = this.parts, [f2, v2] = N(t2, i2);
    if (this.el = S.createElement(f2, e2), P.currentNode = this.el.content, 2 === i2 || 3 === i2) {
      const t3 = this.el.content.firstChild;
      t3.replaceWith(...t3.childNodes);
    }
    for (; null !== (r2 = P.nextNode()) && d2.length < u2; ) {
      if (1 === r2.nodeType) {
        if (r2.hasAttributes()) for (const t3 of r2.getAttributeNames()) if (t3.endsWith(h)) {
          const i3 = v2[a2++], s2 = r2.getAttribute(t3).split(o$2), e3 = /([.?@])?(.*)/.exec(i3);
          d2.push({ type: 1, index: l2, name: e3[2], strings: s2, ctor: "." === e3[1] ? I : "?" === e3[1] ? L : "@" === e3[1] ? z : H }), r2.removeAttribute(t3);
        } else t3.startsWith(o$2) && (d2.push({ type: 6, index: l2 }), r2.removeAttribute(t3));
        if (y2.test(r2.tagName)) {
          const t3 = r2.textContent.split(o$2), i3 = t3.length - 1;
          if (i3 > 0) {
            r2.textContent = s$1 ? s$1.emptyScript : "";
            for (let s2 = 0; s2 < i3; s2++) r2.append(t3[s2], c()), P.nextNode(), d2.push({ type: 2, index: ++l2 });
            r2.append(t3[i3], c());
          }
        }
      } else if (8 === r2.nodeType) if (r2.data === n$1) d2.push({ type: 2, index: l2 });
      else {
        let t3 = -1;
        for (; -1 !== (t3 = r2.data.indexOf(o$2, t3 + 1)); ) d2.push({ type: 7, index: l2 }), t3 += o$2.length - 1;
      }
      l2++;
    }
  }
  static createElement(t2, i2) {
    const s2 = l.createElement("template");
    return s2.innerHTML = t2, s2;
  }
}
function M(t2, i2, s2 = t2, e2) {
  if (i2 === E) return i2;
  let h2 = void 0 !== e2 ? s2._$Co?.[e2] : s2._$Cl;
  const o2 = a(i2) ? void 0 : i2._$litDirective$;
  return h2?.constructor !== o2 && (h2?._$AO?.(false), void 0 === o2 ? h2 = void 0 : (h2 = new o2(t2), h2._$AT(t2, s2, e2)), void 0 !== e2 ? (s2._$Co ??= [])[e2] = h2 : s2._$Cl = h2), void 0 !== h2 && (i2 = M(t2, h2._$AS(t2, i2.values), h2, e2)), i2;
}
class R {
  constructor(t2, i2) {
    this._$AV = [], this._$AN = void 0, this._$AD = t2, this._$AM = i2;
  }
  get parentNode() {
    return this._$AM.parentNode;
  }
  get _$AU() {
    return this._$AM._$AU;
  }
  u(t2) {
    const { el: { content: i2 }, parts: s2 } = this._$AD, e2 = (t2?.creationScope ?? l).importNode(i2, true);
    P.currentNode = e2;
    let h2 = P.nextNode(), o2 = 0, n3 = 0, r2 = s2[0];
    for (; void 0 !== r2; ) {
      if (o2 === r2.index) {
        let i3;
        2 === r2.type ? i3 = new k(h2, h2.nextSibling, this, t2) : 1 === r2.type ? i3 = new r2.ctor(h2, r2.name, r2.strings, this, t2) : 6 === r2.type && (i3 = new Z(h2, this, t2)), this._$AV.push(i3), r2 = s2[++n3];
      }
      o2 !== r2?.index && (h2 = P.nextNode(), o2++);
    }
    return P.currentNode = l, e2;
  }
  p(t2) {
    let i2 = 0;
    for (const s2 of this._$AV) void 0 !== s2 && (void 0 !== s2.strings ? (s2._$AI(t2, s2, i2), i2 += s2.strings.length - 2) : s2._$AI(t2[i2])), i2++;
  }
}
class k {
  get _$AU() {
    return this._$AM?._$AU ?? this._$Cv;
  }
  constructor(t2, i2, s2, e2) {
    this.type = 2, this._$AH = A, this._$AN = void 0, this._$AA = t2, this._$AB = i2, this._$AM = s2, this.options = e2, this._$Cv = e2?.isConnected ?? true;
  }
  get parentNode() {
    let t2 = this._$AA.parentNode;
    const i2 = this._$AM;
    return void 0 !== i2 && 11 === t2?.nodeType && (t2 = i2.parentNode), t2;
  }
  get startNode() {
    return this._$AA;
  }
  get endNode() {
    return this._$AB;
  }
  _$AI(t2, i2 = this) {
    t2 = M(this, t2, i2), a(t2) ? t2 === A || null == t2 || "" === t2 ? (this._$AH !== A && this._$AR(), this._$AH = A) : t2 !== this._$AH && t2 !== E && this._(t2) : void 0 !== t2._$litType$ ? this.$(t2) : void 0 !== t2.nodeType ? this.T(t2) : d(t2) ? this.k(t2) : this._(t2);
  }
  O(t2) {
    return this._$AA.parentNode.insertBefore(t2, this._$AB);
  }
  T(t2) {
    this._$AH !== t2 && (this._$AR(), this._$AH = this.O(t2));
  }
  _(t2) {
    this._$AH !== A && a(this._$AH) ? this._$AA.nextSibling.data = t2 : this.T(l.createTextNode(t2)), this._$AH = t2;
  }
  $(t2) {
    const { values: i2, _$litType$: s2 } = t2, e2 = "number" == typeof s2 ? this._$AC(t2) : (void 0 === s2.el && (s2.el = S.createElement(V(s2.h, s2.h[0]), this.options)), s2);
    if (this._$AH?._$AD === e2) this._$AH.p(i2);
    else {
      const t3 = new R(e2, this), s3 = t3.u(this.options);
      t3.p(i2), this.T(s3), this._$AH = t3;
    }
  }
  _$AC(t2) {
    let i2 = C.get(t2.strings);
    return void 0 === i2 && C.set(t2.strings, i2 = new S(t2)), i2;
  }
  k(t2) {
    u(this._$AH) || (this._$AH = [], this._$AR());
    const i2 = this._$AH;
    let s2, e2 = 0;
    for (const h2 of t2) e2 === i2.length ? i2.push(s2 = new k(this.O(c()), this.O(c()), this, this.options)) : s2 = i2[e2], s2._$AI(h2), e2++;
    e2 < i2.length && (this._$AR(s2 && s2._$AB.nextSibling, e2), i2.length = e2);
  }
  _$AR(t2 = this._$AA.nextSibling, s2) {
    for (this._$AP?.(false, true, s2); t2 !== this._$AB; ) {
      const s3 = i$1(t2).nextSibling;
      i$1(t2).remove(), t2 = s3;
    }
  }
  setConnected(t2) {
    void 0 === this._$AM && (this._$Cv = t2, this._$AP?.(t2));
  }
}
class H {
  get tagName() {
    return this.element.tagName;
  }
  get _$AU() {
    return this._$AM._$AU;
  }
  constructor(t2, i2, s2, e2, h2) {
    this.type = 1, this._$AH = A, this._$AN = void 0, this.element = t2, this.name = i2, this._$AM = e2, this.options = h2, s2.length > 2 || "" !== s2[0] || "" !== s2[1] ? (this._$AH = Array(s2.length - 1).fill(new String()), this.strings = s2) : this._$AH = A;
  }
  _$AI(t2, i2 = this, s2, e2) {
    const h2 = this.strings;
    let o2 = false;
    if (void 0 === h2) t2 = M(this, t2, i2, 0), o2 = !a(t2) || t2 !== this._$AH && t2 !== E, o2 && (this._$AH = t2);
    else {
      const e3 = t2;
      let n3, r2;
      for (t2 = h2[0], n3 = 0; n3 < h2.length - 1; n3++) r2 = M(this, e3[s2 + n3], i2, n3), r2 === E && (r2 = this._$AH[n3]), o2 ||= !a(r2) || r2 !== this._$AH[n3], r2 === A ? t2 = A : t2 !== A && (t2 += (r2 ?? "") + h2[n3 + 1]), this._$AH[n3] = r2;
    }
    o2 && !e2 && this.j(t2);
  }
  j(t2) {
    t2 === A ? this.element.removeAttribute(this.name) : this.element.setAttribute(this.name, t2 ?? "");
  }
}
class I extends H {
  constructor() {
    super(...arguments), this.type = 3;
  }
  j(t2) {
    this.element[this.name] = t2 === A ? void 0 : t2;
  }
}
class L extends H {
  constructor() {
    super(...arguments), this.type = 4;
  }
  j(t2) {
    this.element.toggleAttribute(this.name, !!t2 && t2 !== A);
  }
}
class z extends H {
  constructor(t2, i2, s2, e2, h2) {
    super(t2, i2, s2, e2, h2), this.type = 5;
  }
  _$AI(t2, i2 = this) {
    if ((t2 = M(this, t2, i2, 0) ?? A) === E) return;
    const s2 = this._$AH, e2 = t2 === A && s2 !== A || t2.capture !== s2.capture || t2.once !== s2.once || t2.passive !== s2.passive, h2 = t2 !== A && (s2 === A || e2);
    e2 && this.element.removeEventListener(this.name, this, s2), h2 && this.element.addEventListener(this.name, this, t2), this._$AH = t2;
  }
  handleEvent(t2) {
    "function" == typeof this._$AH ? this._$AH.call(this.options?.host ?? this.element, t2) : this._$AH.handleEvent(t2);
  }
}
class Z {
  constructor(t2, i2, s2) {
    this.element = t2, this.type = 6, this._$AN = void 0, this._$AM = i2, this.options = s2;
  }
  get _$AU() {
    return this._$AM._$AU;
  }
  _$AI(t2) {
    M(this, t2);
  }
}
const B = t$2.litHtmlPolyfillSupport;
B?.(S, k), (t$2.litHtmlVersions ??= []).push("3.3.3");
const D = (t2, i2, s2) => {
  const e2 = s2?.renderBefore ?? i2;
  let h2 = e2._$litPart$;
  if (void 0 === h2) {
    const t3 = s2?.renderBefore ?? null;
    e2._$litPart$ = h2 = new k(i2.insertBefore(c(), t3), t3, void 0, s2 ?? {});
  }
  return h2._$AI(t2), h2;
};
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const s = globalThis;
class i extends y$1 {
  constructor() {
    super(...arguments), this.renderOptions = { host: this }, this._$Do = void 0;
  }
  createRenderRoot() {
    const t2 = super.createRenderRoot();
    return this.renderOptions.renderBefore ??= t2.firstChild, t2;
  }
  update(t2) {
    const r2 = this.render();
    this.hasUpdated || (this.renderOptions.isConnected = this.isConnected), super.update(t2), this._$Do = D(r2, this.renderRoot, this.renderOptions);
  }
  connectedCallback() {
    super.connectedCallback(), this._$Do?.setConnected(true);
  }
  disconnectedCallback() {
    super.disconnectedCallback(), this._$Do?.setConnected(false);
  }
  render() {
    return E;
  }
}
i._$litElement$ = true, i["finalized"] = true, s.litElementHydrateSupport?.({ LitElement: i });
const o$1 = s.litElementPolyfillSupport;
o$1?.({ LitElement: i });
(s.litElementVersions ??= []).push("4.2.2");
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const t$1 = (t2) => (e2, o2) => {
  void 0 !== o2 ? o2.addInitializer(() => {
    customElements.define(t2, e2);
  }) : customElements.define(t2, e2);
};
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const o = { attribute: true, type: String, converter: u$1, reflect: false, hasChanged: f$1 }, r$1 = (t2 = o, e2, r2) => {
  const { kind: n3, metadata: i2 } = r2;
  let s2 = globalThis.litPropertyMetadata.get(i2);
  if (void 0 === s2 && globalThis.litPropertyMetadata.set(i2, s2 = /* @__PURE__ */ new Map()), "setter" === n3 && ((t2 = Object.create(t2)).wrapped = true), s2.set(r2.name, t2), "accessor" === n3) {
    const { name: o2 } = r2;
    return { set(r3) {
      const n4 = e2.get.call(this);
      e2.set.call(this, r3), this.requestUpdate(o2, n4, t2, true, r3);
    }, init(e3) {
      return void 0 !== e3 && this.C(o2, void 0, t2, e3), e3;
    } };
  }
  if ("setter" === n3) {
    const { name: o2 } = r2;
    return function(r3) {
      const n4 = this[o2];
      e2.call(this, r3), this.requestUpdate(o2, n4, t2, true, r3);
    };
  }
  throw Error("Unsupported decorator location: " + n3);
};
function n2(t2) {
  return (e2, o2) => "object" == typeof o2 ? r$1(t2, e2, o2) : ((t3, e3, o3) => {
    const r2 = e3.hasOwnProperty(o3);
    return e3.constructor.createProperty(o3, t3), r2 ? Object.getOwnPropertyDescriptor(e3, o3) : void 0;
  })(t2, e2, o2);
}
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
function r(r2) {
  return n2({ ...r2, state: true, attribute: false });
}
const STRINGS = {
  en: {
    card_name: "Danfoss Ally — Schedule",
    card_description: "Weekly schedule of a Danfoss Ally room (cloud). Minimal card — editing comes later.",
    no_room: "No room selected",
    unknown_room: "Unknown room ({id})",
    version: "Version {version}",
    reload_available: "A new version of the card is available.",
    reload: "Reload",
    pick_room: "Room",
    rooms_unavailable: "Room list unavailable (the integration may not expose it yet).",
    read_only: "Read-only (not an administrator).",
    comfort: "Comfort",
    setback: "Setback",
    refresh: "Refresh",
    last_read: "Last read {when}",
    never_read: "Not read yet",
    schedule_unavailable: "Schedule unavailable (not yet exposed by the integration).",
    setback_all_day: "Setback all day",
    heads_heading: "Thermostats",
    heads_none: "No thermostat in this room.",
    head_online: "Online",
    head_offline: "Offline",
    head_schedule_on: "Schedule active",
    head_schedule_off: "Not following the schedule",
    head_inconsistent: "Inconsistent (left in manual mode)",
    head_mounting: "Mounting mode (not regulating)",
    day_mon: "Mon",
    day_tue: "Tue",
    day_wed: "Wed",
    day_thu: "Thu",
    day_fri: "Fri",
    day_sat: "Sat",
    day_sun: "Sun",
    range_label: "Comfort {start}–{end}",
    degree: "{value} °C",
    // --- Lot 5 : édition ---
    edit: "Edit",
    cancel: "Cancel",
    save: "Save",
    saving: "Saving…",
    discard: "Discard changes",
    add_range: "Add a range",
    delete_range: "Delete this range",
    range_start: "Start",
    range_end: "End",
    transitions_count: "{n} / {max}",
    transitions_aria: "{day}: {n} of {max} transitions",
    transitions_label: "transitions",
    midnight_note: "The thermostat drops the midnight step and keeps the previous evening setpoint until the first range.",
    copy_day: "Copy to…",
    copy_apply: "Copy",
    copy_cancel: "Close",
    copy_heading: "Copy {day} to:",
    copy_select_all: "All days",
    no_changes: "No unsaved changes.",
    save_blocked: "Fix the invalid days before saving.",
    unsaved_hint: "Unsaved changes — save or discard.",
    leave_confirm: "Discard your unsaved schedule changes?",
    beforeunload: "You have unsaved schedule changes.",
    // Erreurs (contrat §5.4)
    err_invalid_time: "Invalid time",
    err_empty_or_reversed: "Empty or reversed range",
    err_overlap: "Overlapping ranges",
    err_too_many_transitions: "Too many transitions (max {max})",
    err_unknown_target: "Unknown room",
    err_grouped_device: "Grouped thermostat: target its room",
    err_not_admin: "You are not an administrator",
    err_cloud_refused: "The cloud refused the change",
    err_session_expired: "Session expired, retry shortly",
    err_unknown: "The change could not be sent",
    // Suivi du lot
    job_heading: "Last send",
    job_status_sent: "Sent to the cloud",
    job_status_applied: "Applied to all thermostats",
    job_status_partial: "Applied to some thermostats",
    job_status_unverified: "Sent (not verified)",
    job_status_failed: "Refused by the cloud",
    head_job_pending: "Pending",
    head_job_applied: "Applied",
    head_job_mismatch: "Different",
    head_job_unreachable: "Unreachable",
    head_job_unverified: "Not verified",
    // Retour au programme (R4)
    restore_schedule: "Back to schedule",
    restore_hint: "A thermostat no longer follows its schedule.",
    restore_done: "Restore sent.",
    // --- Axe D : carte pièce + panneau ---
    room_card_name: "Danfoss Ally — Room",
    room_card_description: "A Danfoss Ally room at a glance: climate, schedule, thermostats and actions.",
    current_temp: "Current {value}",
    setpoint_label: "Setpoint {value}",
    mode_label: "Mode {mode}",
    mode_at_home: "Comfort",
    mode_leaving_home: "Setback",
    mode_manual: "Manual",
    mode_pause: "Pause",
    mode_holiday: "Holiday",
    warmer: "Warmer",
    cooler: "Cooler",
    edit_schedule: "Edit schedule",
    setpoint_readonly: "Setpoint set from the schedule or the thermostat.",
    head_battery: "Battery {value}%",
    head_valve: "Valve {value}%",
    head_window_open: "Window open",
    head_low_battery: "Low battery",
    head_child_lock: "Child lock",
    head_fault: "Fault {code}",
    // Panneau (vue d'ensemble)
    panel_title: "Danfoss Ally — Building",
    overview_unavailable: "Fleet overview unavailable (the integration may not expose it yet).",
    fleet_rooms: "Rooms",
    fleet_heads: "Thermostats",
    fleet_gateways: "Gateways",
    fleet_offline: "Offline",
    fleet_low_battery: "Low battery",
    fleet_heating: "Calling for heat",
    fleet_faults: "Faults",
    fleet_relays_on: "Relays on",
    holiday_active: "Holiday",
    gateway_online: "{n} online",
    rooms_calling: "{n} calling for heat",
    relay_on: "On",
    relay_off: "Off",
    room_offline_n: "{n} offline",
    room_low_battery_n: "{n} low battery",
    room_faults_n: "{n} faults",
    room_calling: "Calling for heat",
    room_window: "Window open",
    room_ok: "OK"
  },
  fr: {
    card_name: "Danfoss Ally — Programme",
    card_description: "Programme hebdomadaire d'une pièce Danfoss Ally (cloud). Carte minimale — l'édition viendra plus tard.",
    no_room: "Aucune pièce choisie",
    unknown_room: "Pièce inconnue ({id})",
    version: "Version {version}",
    reload_available: "Une nouvelle version de la carte est disponible.",
    reload: "Recharger",
    pick_room: "Pièce",
    rooms_unavailable: "Liste des pièces indisponible (l'intégration ne l'expose peut-être pas encore).",
    read_only: "Lecture seule (pas administrateur).",
    comfort: "Confort",
    setback: "Réduit",
    refresh: "Actualiser",
    last_read: "Dernière lecture {when}",
    never_read: "Pas encore lu",
    schedule_unavailable: "Programme indisponible (pas encore exposé par l'intégration).",
    setback_all_day: "Réduit toute la journée",
    heads_heading: "Têtes",
    heads_none: "Aucune tête dans cette pièce.",
    head_online: "En ligne",
    head_offline: "Hors ligne",
    head_schedule_on: "Programme actif",
    head_schedule_off: "Ne suit pas le programme",
    head_inconsistent: "Incohérente (restée en manuel)",
    head_mounting: "Mode montage (ne régule pas)",
    day_mon: "Lun",
    day_tue: "Mar",
    day_wed: "Mer",
    day_thu: "Jeu",
    day_fri: "Ven",
    day_sat: "Sam",
    day_sun: "Dim",
    range_label: "Confort {start}–{end}",
    degree: "{value} °C",
    // --- Lot 5 : édition ---
    edit: "Modifier",
    cancel: "Annuler",
    save: "Enregistrer",
    saving: "Enregistrement…",
    discard: "Annuler les modifications",
    add_range: "Ajouter une plage",
    delete_range: "Supprimer cette plage",
    range_start: "Début",
    range_end: "Fin",
    transitions_count: "{n} / {max}",
    transitions_aria: "{day} : {n} transitions sur {max}",
    transitions_label: "transitions",
    midnight_note: "La tête abandonne la transition de minuit et garde, jusqu'à la première plage, la consigne de la veille au soir.",
    copy_day: "Copier vers…",
    copy_apply: "Copier",
    copy_cancel: "Fermer",
    copy_heading: "Copier {day} vers :",
    copy_select_all: "Tous les jours",
    no_changes: "Aucune modification à enregistrer.",
    save_blocked: "Corrigez les jours invalides avant d'enregistrer.",
    unsaved_hint: "Modifications non enregistrées — enregistrez ou annulez.",
    leave_confirm: "Abandonner les modifications non enregistrées du programme ?",
    beforeunload: "Des modifications du programme ne sont pas enregistrées.",
    // Erreurs (contrat §5.4)
    err_invalid_time: "Heure invalide",
    err_empty_or_reversed: "Plage vide ou inversée",
    err_overlap: "Plages qui se chevauchent",
    err_too_many_transitions: "Trop de transitions (max {max})",
    err_unknown_target: "Pièce inconnue",
    err_grouped_device: "Tête groupée : visez sa pièce",
    err_not_admin: "Vous n'êtes pas administrateur",
    err_cloud_refused: "Le cloud a refusé la modification",
    err_session_expired: "Session expirée, réessayez dans un instant",
    err_unknown: "La modification n'a pas pu être envoyée",
    // Suivi du lot
    job_heading: "Dernier envoi",
    job_status_sent: "Envoyé au cloud",
    job_status_applied: "Appliqué sur toutes les têtes",
    job_status_partial: "Appliqué sur une partie des têtes",
    job_status_unverified: "Envoyé (non vérifié)",
    job_status_failed: "Refusé par le cloud",
    head_job_pending: "En attente",
    head_job_applied: "Appliqué",
    head_job_mismatch: "Différent",
    head_job_unreachable: "Injoignable",
    head_job_unverified: "Non vérifié",
    // Retour au programme (R4)
    restore_schedule: "Revenir au programme",
    restore_hint: "Une tête ne suit plus son programme.",
    restore_done: "Retour au programme envoyé.",
    // --- Axe D : carte pièce + panneau ---
    room_card_name: "Danfoss Ally — Pièce",
    room_card_description: "Une pièce Danfoss Ally d'un coup d'œil : climat, programme, têtes et actions.",
    current_temp: "Actuel {value}",
    setpoint_label: "Consigne {value}",
    mode_label: "Mode {mode}",
    mode_at_home: "Confort",
    mode_leaving_home: "Réduit",
    mode_manual: "Manuel",
    mode_pause: "Pause",
    mode_holiday: "Vacances",
    warmer: "Plus chaud",
    cooler: "Plus froid",
    edit_schedule: "Modifier le programme",
    setpoint_readonly: "Consigne définie par le programme ou le thermostat.",
    head_battery: "Batterie {value} %",
    head_valve: "Vanne {value} %",
    head_window_open: "Fenêtre ouverte",
    head_low_battery: "Batterie faible",
    head_child_lock: "Verrouillage enfant",
    head_fault: "Défaut {code}",
    // Panneau (vue d'ensemble)
    panel_title: "Danfoss Ally — Bâtiment",
    overview_unavailable: "Vue d'ensemble indisponible (l'intégration ne l'expose peut-être pas encore).",
    fleet_rooms: "Pièces",
    fleet_heads: "Têtes",
    fleet_gateways: "Passerelles",
    fleet_offline: "Hors ligne",
    fleet_low_battery: "Batterie faible",
    fleet_heating: "En demande de chauffe",
    fleet_faults: "Défauts",
    fleet_relays_on: "Relais actifs",
    holiday_active: "Vacances",
    gateway_online: "{n} en ligne",
    rooms_calling: "{n} en demande de chauffe",
    relay_on: "Marche",
    relay_off: "Arrêt",
    room_offline_n: "{n} hors ligne",
    room_low_battery_n: "{n} batterie faible",
    room_faults_n: "{n} défauts",
    room_calling: "Demande de chauffe",
    room_window: "Fenêtre ouverte",
    room_ok: "OK"
  }
};
function lang(hass) {
  const code = (hass?.language ?? "en").toLowerCase();
  return code.startsWith("fr") ? "fr" : "en";
}
function t(hass, key, vars = {}) {
  const dict = STRINGS[lang(hass)];
  let text = dict[key] ?? STRINGS.en[key] ?? String(key);
  for (const [name, value] of Object.entries(vars)) {
    text = text.replace(`{${name}}`, String(value));
  }
  return text;
}
const DAY_LABEL_KEYS = {
  mon: "day_mon",
  tue: "day_tue",
  wed: "day_wed",
  thu: "day_thu",
  fri: "day_fri",
  sat: "day_sat",
  sun: "day_sun"
};
function dayLabel(hass, day) {
  return t(hass, DAY_LABEL_KEYS[day]);
}
function language(hass) {
  return lang(hass);
}
const ERROR_KEYS = /* @__PURE__ */ new Set([
  "err_invalid_time",
  "err_empty_or_reversed",
  "err_overlap",
  "err_too_many_transitions",
  "err_unknown_target",
  "err_grouped_device",
  "err_not_admin",
  "err_cloud_refused",
  "err_session_expired",
  "err_unknown"
]);
function errorText(hass, code, vars = {}) {
  const key = `err_${code}`;
  return t(hass, ERROR_KEYS.has(key) ? key : "err_unknown", vars);
}
async function fetchInfo(hass) {
  try {
    return await hass.callWS({ type: "danfoss_ally_cloud/info" });
  } catch {
    return null;
  }
}
async function fetchRooms(hass) {
  try {
    const res = await hass.callWS({
      type: "danfoss_ally_cloud/rooms"
    });
    return res?.rooms ?? [];
  } catch {
    return [];
  }
}
function pickRoom(rooms, roomId) {
  if (!roomId) {
    return void 0;
  }
  return rooms.find((room) => room.id === roomId);
}
async function fetchSchedule(hass, target, refresh = false) {
  try {
    return await hass.callWS({
      type: "danfoss_ally_cloud/schedule/get",
      target,
      refresh
    });
  } catch {
    return null;
  }
}
class ScheduleCommandError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
    this.name = "ScheduleCommandError";
  }
}
function toCommandError(err) {
  if (err && typeof err === "object" && "code" in err) {
    const e2 = err;
    return new ScheduleCommandError(
      typeof e2.code === "string" ? e2.code : "unknown",
      typeof e2.message === "string" ? e2.message : String(e2.code)
    );
  }
  return new ScheduleCommandError("unknown", err instanceof Error ? err.message : String(err));
}
async function validateSchedule(hass, days) {
  try {
    return await hass.callWS({
      type: "danfoss_ally_cloud/schedule/validate",
      days
    });
  } catch {
    return null;
  }
}
async function setSchedule(hass, target, days) {
  try {
    return await hass.callWS({
      type: "danfoss_ally_cloud/schedule/set",
      target,
      days
    });
  } catch (err) {
    throw toCommandError(err);
  }
}
async function restoreSchedule(hass, target) {
  try {
    return await hass.callWS({
      type: "danfoss_ally_cloud/schedule/restore",
      target
    });
  } catch (err) {
    throw toCommandError(err);
  }
}
async function subscribeJobs(hass, callback) {
  if (!hass.connection) {
    return () => {
    };
  }
  try {
    return await hass.connection.subscribeMessage(callback, {
      type: "danfoss_ally_cloud/jobs/subscribe"
    });
  } catch {
    return () => {
    };
  }
}
var __defProp$1 = Object.defineProperty;
var __getOwnPropDesc$1 = Object.getOwnPropertyDescriptor;
var __decorateClass$1 = (decorators, target, key, kind) => {
  var result = kind > 1 ? void 0 : kind ? __getOwnPropDesc$1(target, key) : target;
  for (var i2 = decorators.length - 1, decorator; i2 >= 0; i2--)
    if (decorator = decorators[i2])
      result = (kind ? decorator(target, key, result) : decorator(result)) || result;
  if (kind && result) __defProp$1(target, key, result);
  return result;
};
let DanfossAllyScheduleCardEditor = class extends i {
  constructor() {
    super(...arguments);
    this._config = {};
    this._rooms = [];
    this._loaded = false;
  }
  setConfig(config) {
    this._config = { ...config };
  }
  updated(changed) {
    if (changed.has("hass") && this.hass && !this._loaded) {
      this._loaded = true;
      void this._load();
    }
  }
  async _load() {
    if (this.hass) {
      this._rooms = await fetchRooms(this.hass);
    }
  }
  _roomChanged(ev) {
    const value = ev.target.value;
    const config = { ...this._config, room_id: value };
    this._config = config;
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config },
        bubbles: true,
        composed: true
      })
    );
  }
  render() {
    return b`
      <div class="editor">
        <label for="room">${t(this.hass, "pick_room")}</label>
        <select id="room" @change=${this._roomChanged}>
          <option value="" ?selected=${!this._config.room_id}>—</option>
          ${this._rooms.map(
      (room) => b`
              <option value=${room.id} ?selected=${room.id === this._config.room_id}>
                ${room.name}
              </option>
            `
    )}
        </select>
        ${this._rooms.length === 0 ? b`<div class="hint">${t(this.hass, "rooms_unavailable")}</div>` : A}
      </div>
    `;
  }
};
DanfossAllyScheduleCardEditor.styles = i$3`
    :host {
      display: block;
    }
    .editor {
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding: 8px 0;
    }
    label {
      font-weight: 500;
      color: var(--primary-text-color);
    }
    select {
      padding: 8px;
      border-radius: 6px;
      border: 1px solid var(--divider-color, #ccc);
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color, #000);
      font: inherit;
    }
    .hint {
      color: var(--secondary-text-color);
      font-size: 0.9rem;
    }
  `;
__decorateClass$1([
  n2({ attribute: false })
], DanfossAllyScheduleCardEditor.prototype, "hass", 2);
__decorateClass$1([
  r()
], DanfossAllyScheduleCardEditor.prototype, "_config", 2);
__decorateClass$1([
  r()
], DanfossAllyScheduleCardEditor.prototype, "_rooms", 2);
__decorateClass$1([
  r()
], DanfossAllyScheduleCardEditor.prototype, "_loaded", 2);
DanfossAllyScheduleCardEditor = __decorateClass$1([
  t$1("danfoss-ally-schedule-card-editor")
], DanfossAllyScheduleCardEditor);
const DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const MINUTES_PER_DAY = 24 * 60;
function parseHHMM(value) {
  const m2 = /^(\d{2}):(\d{2})$/.exec(value);
  if (!m2) {
    return null;
  }
  const hours = Number(m2[1]);
  const minutes = Number(m2[2]);
  if (hours > 23 || minutes > 59) {
    return null;
  }
  return hours * 60 + minutes;
}
function dayBars(ranges) {
  const bars = [];
  for (const range of ranges) {
    const start = parseHHMM(range.start);
    const end = parseHHMM(range.end);
    if (start === null || end === null || end <= start) {
      continue;
    }
    bars.push({
      start: range.start,
      end: range.end,
      leftPct: start / MINUTES_PER_DAY * 100,
      widthPct: (end - start) / MINUTES_PER_DAY * 100
    });
  }
  bars.sort((a2, b2) => a2.leftPct - b2.leftPct);
  return bars;
}
function isSetbackOnly(ranges) {
  return dayBars(ranges).length === 0;
}
function formatReadAt(iso, lang2) {
  if (!iso) {
    return null;
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return new Intl.DateTimeFormat(lang2, {
    dateStyle: "short",
    timeStyle: "short"
  }).format(date);
}
const SNAP_MINUTES = 5;
const MIN_RANGE_MINUTES = SNAP_MINUTES;
const LAST_MINUTE = 23 * 60 + 59;
function formatHHMM(minutes) {
  const m2 = (Math.round(minutes) % 1440 + 1440) % 1440;
  const h2 = Math.floor(m2 / 60);
  return `${String(h2).padStart(2, "0")}:${String(m2 % 60).padStart(2, "0")}`;
}
function snapMinutes(minutes) {
  const snapped = Math.round(minutes / SNAP_MINUTES) * SNAP_MINUTES;
  return Math.max(0, Math.min(LAST_MINUTE, snapped));
}
function replace(ranges, index, next) {
  return ranges.map((r2, i2) => i2 === index ? next : r2);
}
function sortRanges(ranges) {
  return [...ranges].sort(
    (a2, b2) => (parseHHMM(a2.start) ?? Infinity) - (parseHHMM(b2.start) ?? Infinity)
  );
}
function firstFreeSlot(ranges, durationMin = 60) {
  const parsed = ranges.map((r2) => ({ s: parseHHMM(r2.start), e: parseHHMM(r2.end) })).filter(
    (r2) => r2.s !== null && r2.e !== null && r2.e > r2.s
  ).sort((a2, b2) => a2.s - b2.s);
  let cursor = 0;
  for (const r2 of parsed) {
    if (r2.s - cursor >= durationMin) {
      return { start: cursor, end: cursor + durationMin };
    }
    cursor = Math.max(cursor, r2.e);
  }
  if (1440 - cursor >= durationMin) {
    return { start: cursor, end: cursor + durationMin };
  }
  return null;
}
function addRange(ranges) {
  if (ranges.length === 0) {
    return [{ start: "08:00", end: "17:00" }];
  }
  const slot = firstFreeSlot(ranges, 60);
  if (!slot) {
    return ranges;
  }
  return sortRanges([
    ...ranges,
    { start: formatHHMM(slot.start), end: formatHHMM(slot.end) }
  ]);
}
function deleteRange(ranges, index) {
  return ranges.filter((_2, i2) => i2 !== index);
}
function moveRange(ranges, index, deltaMin) {
  const r2 = ranges[index];
  if (!r2) {
    return ranges;
  }
  const s2 = parseHHMM(r2.start);
  const e2 = parseHHMM(r2.end);
  if (s2 === null || e2 === null) {
    return ranges;
  }
  const dur = e2 - s2;
  let ns = snapMinutes(s2 + deltaMin);
  if (ns + dur > LAST_MINUTE) {
    ns = LAST_MINUTE - dur;
  }
  if (ns < 0) {
    ns = 0;
  }
  return replace(ranges, index, { start: formatHHMM(ns), end: formatHHMM(ns + dur) });
}
function resizeRange(ranges, index, edge, deltaMin) {
  const r2 = ranges[index];
  if (!r2) {
    return ranges;
  }
  const s2 = parseHHMM(r2.start);
  const e2 = parseHHMM(r2.end);
  if (s2 === null || e2 === null) {
    return ranges;
  }
  if (edge === "start") {
    const ns = Math.min(snapMinutes(s2 + deltaMin), e2 - MIN_RANGE_MINUTES);
    return replace(ranges, index, { start: formatHHMM(Math.max(0, ns)), end: r2.end });
  }
  const ne = Math.max(snapMinutes(e2 + deltaMin), s2 + MIN_RANGE_MINUTES);
  return replace(ranges, index, { start: r2.start, end: formatHHMM(Math.min(LAST_MINUTE, ne)) });
}
function setRangeTime(ranges, index, edge, value) {
  const r2 = ranges[index];
  if (!r2) {
    return ranges;
  }
  return replace(ranges, index, edge === "start" ? { ...r2, start: value } : { ...r2, end: value });
}
function cloneDays(days) {
  const out = {};
  for (const [day, ranges] of Object.entries(days)) {
    out[day] = ranges.map((r2) => ({ ...r2 }));
  }
  return out;
}
function copyDay(days, from, targets) {
  const source = (days[from] ?? []).map((r2) => ({ ...r2 }));
  const out = cloneDays(days);
  for (const target of targets) {
    if (target !== from) {
      out[target] = source.map((r2) => ({ ...r2 }));
    }
  }
  return out;
}
function fingerprint(ranges) {
  return sortRanges(ranges).map((r2) => `${r2.start}-${r2.end}`).join("|");
}
function rangesEqual(a2, b2) {
  return fingerprint(a2) === fingerprint(b2);
}
function modifiedDays(original, draft, dayKeys) {
  return dayKeys.filter((day) => !rangesEqual(original[day] ?? [], draft[day] ?? []));
}
const MAX_TRANSITIONS_PER_DAY = 6;
function countTransitions(ranges) {
  const starts = new Set(ranges.map((r2) => r2.start));
  let count = 0;
  for (const r2 of ranges) {
    if (r2.start !== 0) {
      count += 1;
    }
    if (!starts.has(r2.end)) {
      count += 1;
    }
  }
  return { count, impliedMidnight: ranges.length > 0 && !starts.has(0) };
}
function validateDay(ranges, day = null) {
  const errors = [];
  const parsed = [];
  for (const range of ranges) {
    const start = parseHHMM(range.start);
    const end = parseHHMM(range.end);
    if (start === null || end === null) {
      errors.push({ code: "invalid_time", day });
      continue;
    }
    if (start >= end) {
      errors.push({ code: "empty_or_reversed", day });
      continue;
    }
    parsed.push({ start, end });
  }
  parsed.sort((a2, b2) => a2.start - b2.start);
  for (let i2 = 1; i2 < parsed.length; i2 += 1) {
    if (parsed[i2].start < parsed[i2 - 1].end) {
      errors.push({ code: "overlap", day });
      break;
    }
  }
  const { count, impliedMidnight } = countTransitions(parsed);
  if (count > MAX_TRANSITIONS_PER_DAY) {
    errors.push({ code: "too_many_transitions", day });
  }
  return {
    transitions: count,
    impliedMidnight,
    valid: errors.length === 0,
    errors
  };
}
const CARD_VERSION = "0.5.0";
function needsReload(cardVersion, serverVersion) {
  if (!serverVersion) {
    return false;
  }
  return cardVersion !== serverVersion;
}
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __decorateClass = (decorators, target, key, kind) => {
  var result = kind > 1 ? void 0 : kind ? __getOwnPropDesc(target, key) : target;
  for (var i2 = decorators.length - 1, decorator; i2 >= 0; i2--)
    if (decorator = decorators[i2])
      result = (kind ? decorator(target, key, result) : decorator(result)) || result;
  if (kind && result) __defProp(target, key, result);
  return result;
};
let DanfossAllyScheduleCard = class extends i {
  constructor() {
    super(...arguments);
    this._rooms = [];
    this._info = null;
    this._schedule = null;
    this._loaded = false;
    this._refreshing = false;
    this._editing = false;
    this._draft = null;
    this._saving = false;
    this._error = null;
    this._job = null;
    this._restoring = false;
    this._copyFrom = null;
    this._copyTargets = /* @__PURE__ */ new Set();
    this._serverValidation = null;
    this._unsubscribe = null;
    this._validateTimer = null;
    this._onBeforeUnload = (ev) => {
      if (this._editing && this._modified.length > 0) {
        ev.preventDefault();
        ev.returnValue = t(this.hass, "beforeunload");
      }
    };
    this._onDragMove = (ev) => {
      if (!this._drag || !this._draft) {
        return;
      }
      const { day, index, mode, startX, trackWidth, orig } = this._drag;
      const deltaMin = (ev.clientX - startX) / trackWidth * 1440;
      const next = mode === "move" ? moveRange(orig, index, deltaMin) : resizeRange(orig, index, mode, deltaMin);
      this._setDay(day, next);
    };
    this._onDragEnd = () => {
      if (this._drag && this._draft) {
        const day = this._drag.day;
        this._setDay(day, sortRanges(this._draft[day] ?? []));
      }
      this._teardownDrag();
    };
  }
  static getConfigElement() {
    return document.createElement("danfoss-ally-schedule-card-editor");
  }
  static getStubConfig() {
    return { room_id: "" };
  }
  setConfig(config) {
    if (!config) {
      throw new Error("Configuration invalide");
    }
    if (this._editing && config.room_id !== this._config?.room_id) {
      this._leaveEdit();
    }
    this._config = config;
  }
  getCardSize() {
    return this._editing ? 12 : 6;
  }
  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsubscribe?.();
    this._unsubscribe = null;
    this._teardownDrag();
    globalThis.removeEventListener?.("beforeunload", this._onBeforeUnload);
  }
  updated(changed) {
    if (changed.has("hass") && this.hass && !this._loaded) {
      this._loaded = true;
      void this._load();
    }
  }
  get _target() {
    const id = this._config?.room_id;
    return id ? { type: "room", id } : void 0;
  }
  async _load() {
    if (!this.hass) {
      return;
    }
    const target = this._target;
    const [info, rooms, schedule] = await Promise.all([
      fetchInfo(this.hass),
      fetchRooms(this.hass),
      target ? fetchSchedule(this.hass, target) : Promise.resolve(null)
    ]);
    this._info = info;
    this._rooms = rooms;
    this._schedule = schedule;
    if (!this._unsubscribe) {
      this._unsubscribe = await subscribeJobs(this.hass, (job) => this._onJob(job));
    }
  }
  _onJob(job) {
    if (job.target?.id === this._config?.room_id) {
      this._job = job;
    }
  }
  async _refresh() {
    const target = this._target;
    if (!this.hass || !target || this._refreshing) {
      return;
    }
    this._refreshing = true;
    try {
      const schedule = await fetchSchedule(this.hass, target, true);
      if (schedule) {
        this._schedule = schedule;
      }
    } finally {
      this._refreshing = false;
    }
  }
  _reload() {
    globalThis.location?.reload();
  }
  // --- Cycle d'édition ---
  get _isAdmin() {
    return this._info !== null && this._info.is_admin;
  }
  get _modified() {
    if (!this._draft || !this._schedule) {
      return [];
    }
    return modifiedDays(this._schedule.days, this._draft, DAY_KEYS);
  }
  get _allValid() {
    if (!this._draft) {
      return true;
    }
    return DAY_KEYS.every((day) => validateDay(this._draft[day] ?? [], day).valid);
  }
  _beginEdit() {
    if (!this._schedule || !this._isAdmin) {
      return;
    }
    this._draft = cloneDays(this._schedule.days);
    this._editing = true;
    this._error = null;
    this._copyFrom = null;
    globalThis.addEventListener?.("beforeunload", this._onBeforeUnload);
  }
  _leaveEdit() {
    this._editing = false;
    this._draft = null;
    this._copyFrom = null;
    this._serverValidation = null;
    this._error = null;
    if (this._validateTimer) {
      clearTimeout(this._validateTimer);
      this._validateTimer = null;
    }
    globalThis.removeEventListener?.("beforeunload", this._onBeforeUnload);
  }
  _cancelEdit() {
    if (this._modified.length > 0) {
      const ok = globalThis.confirm?.(t(this.hass, "leave_confirm"));
      if (ok === false) {
        return;
      }
    }
    this._leaveEdit();
  }
  _setDay(day, ranges) {
    if (!this._draft) {
      return;
    }
    this._draft = { ...this._draft, [day]: ranges };
    this._queueServerValidate();
  }
  /** Validation serveur (débatée) des jours modifiés, en plus de la locale. */
  _queueServerValidate() {
    if (!this.hass) {
      return;
    }
    if (this._validateTimer) {
      clearTimeout(this._validateTimer);
    }
    this._validateTimer = setTimeout(() => {
      void this._runServerValidate();
    }, 300);
  }
  async _runServerValidate() {
    if (!this.hass || !this._draft) {
      return;
    }
    const days = {};
    for (const day of this._modified) {
      days[day] = this._draft[day];
    }
    this._serverValidation = await validateSchedule(this.hass, days);
  }
  // --- Opérations d'édition ---
  _addRange(day) {
    if (!this._draft) {
      return;
    }
    this._setDay(day, addRange(this._draft[day] ?? []));
  }
  _deleteRange(day, index) {
    if (!this._draft) {
      return;
    }
    this._setDay(day, deleteRange(this._draft[day] ?? [], index));
  }
  _onTimeInput(day, index, edge, ev) {
    if (!this._draft) {
      return;
    }
    const value = ev.target.value;
    if (!value) {
      return;
    }
    this._setDay(day, setRangeTime(this._draft[day] ?? [], index, edge, value));
  }
  // --- Copier un jour ---
  _openCopy(day) {
    this._copyFrom = this._copyFrom === day ? null : day;
    this._copyTargets = /* @__PURE__ */ new Set();
  }
  _toggleCopyTarget(day) {
    const next = new Set(this._copyTargets);
    if (next.has(day)) {
      next.delete(day);
    } else {
      next.add(day);
    }
    this._copyTargets = next;
  }
  _toggleCopyAll() {
    if (!this._copyFrom) {
      return;
    }
    const others = DAY_KEYS.filter((d2) => d2 !== this._copyFrom);
    this._copyTargets = this._copyTargets.size === others.length ? /* @__PURE__ */ new Set() : new Set(others);
  }
  _applyCopy() {
    if (!this._draft || !this._copyFrom || this._copyTargets.size === 0) {
      return;
    }
    this._draft = copyDay(this._draft, this._copyFrom, [...this._copyTargets]);
    this._copyFrom = null;
    this._copyTargets = /* @__PURE__ */ new Set();
    this._queueServerValidate();
  }
  // --- Enregistrement / retour au programme ---
  async _save() {
    const target = this._target;
    if (!this.hass || !target || !this._draft || this._saving) {
      return;
    }
    const modified = this._modified;
    if (modified.length === 0 || !this._allValid) {
      return;
    }
    this._saving = true;
    this._error = null;
    const days = {};
    for (const day of modified) {
      days[day] = sortRanges(this._draft[day] ?? []);
    }
    try {
      const job = await setSchedule(this.hass, target, days);
      this._job = job;
      if (this._schedule) {
        this._schedule = { ...this._schedule, days: cloneDays(this._draft) };
      }
      this._leaveEdit();
    } catch (err) {
      const code = err instanceof ScheduleCommandError ? err.code : "unknown";
      this._error = errorText(this.hass, code, { max: MAX_TRANSITIONS_PER_DAY });
    } finally {
      this._saving = false;
    }
  }
  async _restore() {
    const target = this._target;
    if (!this.hass || !target || this._restoring) {
      return;
    }
    this._restoring = true;
    this._error = null;
    try {
      this._job = await restoreSchedule(this.hass, target);
    } catch (err) {
      const code = err instanceof ScheduleCommandError ? err.code : "unknown";
      this._error = errorText(this.hass, code);
    } finally {
      this._restoring = false;
    }
  }
  // --- Glisser-déposer (pointeur) : déplacer / redimensionner une plage ---
  _onBarPointerDown(day, index, mode, ev) {
    if (!this._draft) {
      return;
    }
    ev.preventDefault();
    ev.stopPropagation();
    const handle = ev.currentTarget;
    const track = handle.closest(".track");
    if (!track) {
      return;
    }
    this._drag = {
      day,
      index,
      mode,
      startX: ev.clientX,
      trackWidth: track.getBoundingClientRect().width || 1,
      orig: (this._draft[day] ?? []).map((r2) => ({ ...r2 }))
    };
    handle.setPointerCapture?.(ev.pointerId);
    globalThis.addEventListener?.("pointermove", this._onDragMove);
    globalThis.addEventListener?.("pointerup", this._onDragEnd);
  }
  _teardownDrag() {
    this._drag = void 0;
    globalThis.removeEventListener?.("pointermove", this._onDragMove);
    globalThis.removeEventListener?.("pointerup", this._onDragEnd);
  }
  // --- Rendu ---
  render() {
    const room = pickRoom(this._rooms, this._config?.room_id);
    const showReload = needsReload(CARD_VERSION, this._info?.version);
    const readOnly = this._info !== null && !this._info.is_admin;
    return b`
      <ha-card>
        <div class="content">
          ${showReload ? this._renderReloadBanner() : A}
          <div class="titlebar">
            <div class="room">${this._roomTitle(room)}</div>
            ${this._renderActions(room)}
          </div>
          ${readOnly ? b`<div class="hint">${t(this.hass, "read_only")}</div>` : A}
          ${this._error ? b`<div class="banner error" role="alert">${this._error}</div>` : A}
          ${this._renderBody(room)}
        </div>
      </ha-card>
    `;
  }
  _renderActions(room) {
    if (!this._isAdmin || !this._schedule) {
      return A;
    }
    if (this._editing) {
      const canSave = this._modified.length > 0 && this._allValid && !this._saving;
      return b`
        <div class="actions">
          <button class="btn ghost" @click=${this._cancelEdit} ?disabled=${this._saving}>
            ${t(this.hass, "cancel")}
          </button>
          <button class="btn primary" @click=${this._save} ?disabled=${!canSave}>
            ${ICON_SAVE}<span>${this._saving ? t(this.hass, "saving") : t(this.hass, "save")}</span>
          </button>
        </div>
      `;
    }
    const needsRestore = (room?.heads ?? []).some((h2) => h2.schedule_active === false);
    return b`
      <div class="actions">
        ${needsRestore ? b`<button
              class="btn ghost"
              @click=${this._restore}
              ?disabled=${this._restoring}
              title=${t(this.hass, "restore_hint")}
            >
              ${ICON_RESTORE}<span>${t(this.hass, "restore_schedule")}</span>
            </button>` : A}
        <button class="btn primary" @click=${this._beginEdit}>
          ${ICON_EDIT}<span>${t(this.hass, "edit")}</span>
        </button>
      </div>
    `;
  }
  _renderBody(room) {
    if (this._rooms.length === 0 && !this._config?.room_id) {
      return b`<div class="hint">${t(this.hass, "rooms_unavailable")}</div>`;
    }
    const schedule = this._schedule;
    const comfort = schedule?.comfort ?? room?.comfort ?? null;
    const setback = schedule?.setback ?? room?.setback ?? null;
    return b`
      ${this._renderSetpoints(comfort, setback)}
      ${this._editing && this._draft ? this._renderEditor() : schedule ? this._renderGrid(schedule) : b`<div class="hint">${t(this.hass, "schedule_unavailable")}</div>`}
      ${this._renderHeads(room)}
      ${this._renderJob()}
      ${this._editing ? this._renderUnsavedHint() : this._renderFooter(schedule)}
    `;
  }
  _roomTitle(room) {
    if (room) {
      return room.name;
    }
    if (this._schedule?.name) {
      return this._schedule.name;
    }
    if (this._config?.room_id) {
      return t(this.hass, "unknown_room", { id: this._config.room_id });
    }
    return t(this.hass, "no_room");
  }
  _renderSetpoints(comfort, setback) {
    const fmt = (v2) => v2 === null ? "—" : t(this.hass, "degree", { value: v2 });
    return b`
      <div class="setpoints">
        <span class="chip comfort">
          <span class="swatch comfort"></span>${t(this.hass, "comfort")} ${fmt(comfort)}
        </span>
        <span class="chip setback">
          <span class="swatch setback"></span>${t(this.hass, "setback")} ${fmt(setback)}
        </span>
      </div>
    `;
  }
  // --- Grille de lecture (lot 4) ---
  _renderGrid(schedule) {
    return b`
      <div class="grid">
        ${this._renderScale()}
        ${DAY_KEYS.map((day) => this._renderDay(day, schedule.days[day] ?? []))}
      </div>
    `;
  }
  _renderScale() {
    return b`
      <div class="scale" aria-hidden="true">
        <span>0 h</span><span>6 h</span><span>12 h</span><span>18 h</span><span>24 h</span>
      </div>
    `;
  }
  _renderDay(day, ranges) {
    const bars = dayBars(ranges);
    const label = this._dayAria(day, bars, isSetbackOnly(ranges));
    return b`
      <div class="day">
        <span class="day-label">${dayLabel(this.hass, day)}</span>
        <div class="track" role="img" aria-label=${label}>
          ${bars.map(
      (bar) => b`
              <div
                class="bar"
                style="left:${bar.leftPct}%;width:${bar.widthPct}%"
                title=${t(this.hass, "range_label", { start: bar.start, end: bar.end })}
              ></div>
            `
    )}
        </div>
      </div>
    `;
  }
  _dayAria(day, bars, setbackOnly) {
    const name = dayLabel(this.hass, day);
    if (setbackOnly) {
      return `${name} — ${t(this.hass, "setback_all_day")}`;
    }
    const parts = bars.map((bar) => t(this.hass, "range_label", { start: bar.start, end: bar.end }));
    return `${name} — ${parts.join(", ")}`;
  }
  // --- Grille d'édition (lot 5) ---
  _renderEditor() {
    return b`
      <div class="grid editing">
        ${this._renderScale()}
        ${DAY_KEYS.map((day) => this._renderEditDay(day))}
      </div>
    `;
  }
  _renderEditDay(day) {
    const ranges = this._draft[day] ?? [];
    const result = validateDay(ranges, day);
    const bars = dayBars(ranges);
    const counterClass = result.valid ? "counter" : "counter invalid";
    const codes = this._dayErrorCodes(day, result.errors.map((e2) => e2.code));
    return b`
      <div class="eday ${result.valid ? "" : "invalid"}">
        <div class="eday-row">
          <span class="day-label">${dayLabel(this.hass, day)}</span>
          <div class="track editable">
            ${bars.map((bar, i2) => this._renderEditBar(day, i2, bar))}
          </div>
          <span
            class=${counterClass}
            aria-label=${t(this.hass, "transitions_aria", {
      day: dayLabel(this.hass, day),
      n: result.transitions,
      max: MAX_TRANSITIONS_PER_DAY
    })}
          >
            ${t(this.hass, "transitions_count", {
      n: result.transitions,
      max: MAX_TRANSITIONS_PER_DAY
    })}
          </span>
        </div>
        <div class="ranges">
          ${sortRanges(ranges).map((r2) => this._rangeRow(day, ranges.indexOf(r2), r2))}
          <div class="range-tools">
            <button class="btn tiny" @click=${() => this._addRange(day)}>
              ${ICON_PLUS}<span>${t(this.hass, "add_range")}</span>
            </button>
            <button
              class="btn tiny"
              @click=${() => this._openCopy(day)}
              ?disabled=${ranges.length === 0 && (this._draft[day]?.length ?? 0) === 0}
              aria-expanded=${this._copyFrom === day ? "true" : "false"}
            >
              ${ICON_COPY}<span>${t(this.hass, "copy_day")}</span>
            </button>
          </div>
        </div>
        ${codes.length > 0 ? b`<div class="errors">
              ${codes.map(
      (code) => b`<span class="err">${errorText(this.hass, code, {
        max: MAX_TRANSITIONS_PER_DAY
      })}</span>`
    )}
            </div>` : result.impliedMidnight && result.transitions === MAX_TRANSITIONS_PER_DAY ? b`<div class="note">${t(this.hass, "midnight_note")}</div>` : A}
        ${this._copyFrom === day ? this._renderCopyPanel(day) : A}
      </div>
    `;
  }
  /** Codes d'erreur à afficher : union locale + serveur, sans doublon. */
  _dayErrorCodes(day, localCodes) {
    const codes = new Set(localCodes);
    for (const e2 of this._serverValidation?.errors ?? []) {
      if (e2.day === day) {
        codes.add(e2.code);
      }
    }
    return [...codes];
  }
  _renderEditBar(day, index, bar) {
    return b`
      <div class="bar edit" style="left:${bar.leftPct}%;width:${bar.widthPct}%">
        <span
          class="grip start"
          @pointerdown=${(ev) => this._onBarPointerDown(day, index, "start", ev)}
        ></span>
        <span
          class="grip body"
          @pointerdown=${(ev) => this._onBarPointerDown(day, index, "move", ev)}
          title=${t(this.hass, "range_label", { start: bar.start, end: bar.end })}
        ></span>
        <span
          class="grip end"
          @pointerdown=${(ev) => this._onBarPointerDown(day, index, "end", ev)}
        ></span>
      </div>
    `;
  }
  _rangeRow(day, index, r2) {
    return b`
      <div class="range">
        <label class="field">
          <span class="field-label">${t(this.hass, "range_start")}</span>
          <input
            type="time"
            step="300"
            .value=${r2.start}
            @change=${(ev) => this._onTimeInput(day, index, "start", ev)}
          />
        </label>
        <span class="dash">–</span>
        <label class="field">
          <span class="field-label">${t(this.hass, "range_end")}</span>
          <input
            type="time"
            step="300"
            .value=${r2.end}
            @change=${(ev) => this._onTimeInput(day, index, "end", ev)}
          />
        </label>
        <button
          class="btn icon"
          @click=${() => this._deleteRange(day, index)}
          aria-label=${t(this.hass, "delete_range")}
          title=${t(this.hass, "delete_range")}
        >
          ${ICON_TRASH}
        </button>
      </div>
    `;
  }
  _renderCopyPanel(day) {
    const others = DAY_KEYS.filter((d2) => d2 !== day);
    const allSelected = this._copyTargets.size === others.length;
    return b`
      <div class="copy-panel">
        <div class="copy-head">${t(this.hass, "copy_heading", { day: dayLabel(this.hass, day) })}</div>
        <div class="copy-days">
          <label class="copy-opt all">
            <input type="checkbox" .checked=${allSelected} @change=${this._toggleCopyAll} />
            <span>${t(this.hass, "copy_select_all")}</span>
          </label>
          ${others.map(
      (d2) => b`
              <label class="copy-opt">
                <input
                  type="checkbox"
                  .checked=${this._copyTargets.has(d2)}
                  @change=${() => this._toggleCopyTarget(d2)}
                />
                <span>${dayLabel(this.hass, d2)}</span>
              </label>
            `
    )}
        </div>
        <div class="copy-actions">
          <button class="btn ghost tiny" @click=${() => this._openCopy(day)}>
            ${t(this.hass, "copy_cancel")}
          </button>
          <button
            class="btn primary tiny"
            @click=${this._applyCopy}
            ?disabled=${this._copyTargets.size === 0}
          >
            ${t(this.hass, "copy_apply")}
          </button>
        </div>
      </div>
    `;
  }
  _renderUnsavedHint() {
    const dirty = this._modified.length > 0;
    return b`
      <div class="footer edit-footer">
        <span class="read-at">${dirty ? t(this.hass, "unsaved_hint") : t(this.hass, "no_changes")}</span>
        <span class="version">${t(this.hass, "version", { version: CARD_VERSION })}</span>
      </div>
    `;
  }
  // --- Têtes, lot, pied ---
  _renderHeads(room) {
    const heads = room?.heads ?? [];
    return b`
      <div class="heads">
        <div class="heads-title">${t(this.hass, "heads_heading")}</div>
        ${heads.length === 0 ? b`<div class="hint">${t(this.hass, "heads_none")}</div>` : b`<div class="heads-list">${heads.map((head) => this._renderHead(head))}</div>`}
      </div>
    `;
  }
  _renderHead(head) {
    const jobHead = this._job?.heads.find((h2) => h2.device_id === head.device_id);
    return b`
      <div class="head">
        <span class="head-name">${head.name}</span>
        <span class="badges">
          ${jobHead ? this._renderJobBadge(jobHead.status) : A}
          ${this._badge(
      head.online ? "ok" : "off",
      head.online ? ICON_WIFI : ICON_WIFI_OFF,
      t(this.hass, head.online ? "head_online" : "head_offline")
    )}
          ${head.schedule_active !== null ? this._badge(
      head.schedule_active ? "ok" : "muted",
      head.schedule_active ? ICON_CHECK : ICON_MINUS,
      t(this.hass, head.schedule_active ? "head_schedule_on" : "head_schedule_off")
    ) : A}
          ${head.inconsistent ? this._badge("warn", ICON_ALERT, t(this.hass, "head_inconsistent")) : A}
          ${head.mounting ? this._badge("muted", ICON_WRENCH, t(this.hass, "head_mounting")) : A}
        </span>
      </div>
    `;
  }
  _renderJobBadge(status) {
    const map = {
      pending: { kind: "muted", key: "head_job_pending" },
      applied: { kind: "ok", key: "head_job_applied" },
      mismatch: { kind: "warn", key: "head_job_mismatch" },
      unreachable: { kind: "off", key: "head_job_unreachable" },
      unverified: { kind: "muted", key: "head_job_unverified" }
    };
    const m2 = map[status] ?? map.pending;
    const label = t(this.hass, m2.key);
    return b`<span class="pill ${m2.kind}" title=${label}>${label}</span>`;
  }
  _badge(kind, icon, label) {
    return b`
      <span class="badge ${kind}" title=${label} role="img" aria-label=${label}>${icon}</span>
    `;
  }
  _renderJob() {
    const job = this._job;
    if (!job) {
      return A;
    }
    const key = `job_status_${job.status}`;
    return b`
      <div class="job">
        <span class="job-title">${t(this.hass, "job_heading")}</span>
        <span class="pill ${this._jobKind(job.status)}">${t(this.hass, key)}</span>
      </div>
    `;
  }
  _jobKind(status) {
    switch (status) {
      case "applied":
        return "ok";
      case "partial":
        return "warn";
      case "failed":
        return "off";
      default:
        return "muted";
    }
  }
  _renderFooter(schedule) {
    const when = formatReadAt(schedule?.read_at, language(this.hass));
    const lastRead = when ? t(this.hass, "last_read", { when }) : t(this.hass, "never_read");
    const canRefresh = Boolean(this.hass && this._target);
    return b`
      <div class="footer">
        <button
          class="refresh"
          @click=${this._refresh}
          ?disabled=${!canRefresh || this._refreshing}
          aria-label=${t(this.hass, "refresh")}
        >
          ${ICON_REFRESH}<span>${t(this.hass, "refresh")}</span>
        </button>
        <span class="read-at">${lastRead}</span>
        <span class="version">${t(this.hass, "version", { version: CARD_VERSION })}</span>
      </div>
    `;
  }
  _renderReloadBanner() {
    return b`
      <div class="reload">
        <span>${t(this.hass, "reload_available")}</span>
        <button @click=${this._reload}>${t(this.hass, "reload")}</button>
      </div>
    `;
  }
};
DanfossAllyScheduleCard.styles = i$3`
    :host {
      display: block;
    }
    .content {
      padding: 0 16px 16px;
    }
    .titlebar {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      padding-top: 16px;
    }
    .room {
      font-size: 1.4rem;
      font-weight: 500;
      color: var(--primary-text-color);
    }
    .actions {
      display: inline-flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .hint {
      margin-top: 8px;
      color: var(--secondary-text-color);
      font-size: 0.9rem;
    }
    .banner {
      margin-top: 10px;
      padding: 8px 12px;
      border-radius: 8px;
      font-size: 0.85rem;
    }
    .banner.error {
      background: var(--error-color, #c62828);
      color: var(--text-primary-color, #fff);
    }
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      cursor: pointer;
      border: 1px solid var(--divider-color, #e0e0e0);
      border-radius: 16px;
      padding: 6px 12px;
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
      font: inherit;
      font-size: 0.85rem;
    }
    .btn svg {
      width: 16px;
      height: 16px;
      fill: currentColor;
    }
    .btn:hover:not(:disabled) {
      background: var(--secondary-background-color, #f0f0f0);
    }
    .btn:disabled {
      opacity: 0.5;
      cursor: default;
    }
    .btn.primary {
      background: var(--primary-color, #03a9f4);
      color: var(--text-primary-color, #fff);
      border-color: transparent;
    }
    .btn.primary:hover:not(:disabled) {
      filter: brightness(0.95);
    }
    .btn.ghost {
      background: transparent;
    }
    .btn.tiny {
      padding: 4px 10px;
      font-size: 0.8rem;
    }
    .btn.icon {
      padding: 4px;
      border-radius: 8px;
    }
    .setpoints {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 12px 0;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 10px;
      border-radius: 14px;
      font-size: 0.9rem;
      background: var(--secondary-background-color, #f0f0f0);
      color: var(--primary-text-color);
    }
    .swatch {
      width: 12px;
      height: 12px;
      border-radius: 3px;
    }
    .swatch.comfort,
    .bar {
      background: var(--danfoss-comfort-color, var(--primary-color, #03a9f4));
    }
    .swatch.setback {
      background: var(--danfoss-setback-color, var(--disabled-text-color, #9e9e9e));
    }
    .grid {
      margin: 8px 0 4px;
    }
    .scale {
      display: flex;
      justify-content: space-between;
      margin: 0 0 4px calc(2.6rem + 8px);
      color: var(--secondary-text-color);
      font-size: 0.7rem;
    }
    .day {
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 3px 0;
    }
    .day-label {
      flex: 0 0 2.6rem;
      font-size: 0.8rem;
      color: var(--secondary-text-color);
    }
    .track {
      position: relative;
      flex: 1 1 auto;
      height: 16px;
      border-radius: 4px;
      background: var(--danfoss-track-color, var(--divider-color, #e0e0e0));
      background-image: linear-gradient(
        to right,
        transparent 0,
        transparent calc(25% - 1px),
        rgba(127, 127, 127, 0.35) calc(25% - 1px),
        rgba(127, 127, 127, 0.35) 25%
      );
      background-size: 25% 100%;
      overflow: hidden;
    }
    .track.editable {
      height: 22px;
      overflow: visible;
    }
    .bar {
      position: absolute;
      top: 0;
      bottom: 0;
      border-radius: 3px;
      min-width: 2px;
    }
    .bar.edit {
      display: flex;
      touch-action: none;
    }
    .grip {
      display: block;
    }
    .grip.body {
      flex: 1 1 auto;
      cursor: grab;
    }
    .grip.start,
    .grip.end {
      flex: 0 0 8px;
      cursor: ew-resize;
      background: rgba(0, 0, 0, 0.25);
    }
    .grip.start {
      border-radius: 3px 0 0 3px;
    }
    .grip.end {
      border-radius: 0 3px 3px 0;
    }
    .eday {
      padding: 6px 0;
      border-bottom: 1px solid var(--divider-color, #eee);
    }
    .eday.invalid {
      background: var(--danfoss-invalid-bg, rgba(198, 40, 40, 0.06));
      border-radius: 6px;
    }
    .eday-row {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .counter {
      flex: 0 0 auto;
      font-size: 0.75rem;
      font-variant-numeric: tabular-nums;
      color: var(--secondary-text-color);
      min-width: 2.4rem;
      text-align: right;
    }
    .counter.invalid {
      color: var(--error-color, #c62828);
      font-weight: 600;
    }
    .ranges {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin: 6px 0 0 calc(2.6rem + 8px);
    }
    .range {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .field {
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .field-label {
      font-size: 0.7rem;
      color: var(--secondary-text-color);
    }
    input[type="time"] {
      font: inherit;
      font-size: 0.85rem;
      padding: 4px 6px;
      border-radius: 6px;
      border: 1px solid var(--divider-color, #ccc);
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color, #000);
      color-scheme: light dark;
    }
    .dash {
      color: var(--secondary-text-color);
    }
    .range-tools {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 2px;
    }
    .errors {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin: 6px 0 0 calc(2.6rem + 8px);
    }
    .err {
      font-size: 0.75rem;
      color: var(--error-color, #c62828);
    }
    .note {
      font-size: 0.72rem;
      color: var(--secondary-text-color);
      margin: 6px 0 0 calc(2.6rem + 8px);
    }
    .copy-panel {
      margin: 8px 0 2px calc(2.6rem + 8px);
      padding: 8px 10px;
      border-radius: 8px;
      background: var(--secondary-background-color, #f3f3f3);
    }
    .copy-head {
      font-size: 0.8rem;
      font-weight: 500;
      margin-bottom: 6px;
    }
    .copy-days {
      display: flex;
      flex-wrap: wrap;
      gap: 4px 12px;
    }
    .copy-opt {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 0.8rem;
      color: var(--primary-text-color);
    }
    .copy-opt.all {
      font-weight: 500;
      flex: 0 0 100%;
    }
    .copy-actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 8px;
    }
    .heads {
      margin-top: 14px;
    }
    .heads-title {
      font-size: 0.85rem;
      font-weight: 500;
      color: var(--secondary-text-color);
      margin-bottom: 6px;
    }
    .heads-list {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }
    .head-name {
      font-size: 0.9rem;
      color: var(--primary-text-color);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .badges {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      flex: 0 0 auto;
    }
    .badge {
      display: inline-flex;
      width: 20px;
      height: 20px;
      align-items: center;
      justify-content: center;
      border-radius: 50%;
    }
    .badge svg {
      width: 15px;
      height: 15px;
      fill: currentColor;
    }
    .badge.ok {
      color: var(--success-color, #2e7d32);
    }
    .badge.warn {
      color: var(--warning-color, #ffa600);
    }
    .badge.off,
    .badge.muted {
      color: var(--disabled-text-color, #9e9e9e);
    }
    .pill {
      font-size: 0.7rem;
      padding: 2px 8px;
      border-radius: 10px;
      background: var(--secondary-background-color, #eee);
      color: var(--primary-text-color);
      white-space: nowrap;
    }
    .pill.ok {
      background: var(--success-color, #2e7d32);
      color: var(--text-primary-color, #fff);
    }
    .pill.warn {
      background: var(--warning-color, #ffa600);
      color: var(--text-primary-color, #fff);
    }
    .pill.off {
      background: var(--disabled-text-color, #9e9e9e);
      color: var(--text-primary-color, #fff);
    }
    .job {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 12px;
    }
    .job-title {
      font-size: 0.8rem;
      color: var(--secondary-text-color);
    }
    .footer {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px 12px;
      margin-top: 16px;
    }
    .refresh {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      cursor: pointer;
      border: 1px solid var(--divider-color, #e0e0e0);
      border-radius: 16px;
      padding: 5px 12px;
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
      font: inherit;
      font-size: 0.85rem;
    }
    .refresh:hover {
      background: var(--secondary-background-color, #f0f0f0);
    }
    .refresh:disabled {
      opacity: 0.6;
      cursor: default;
    }
    .refresh svg {
      width: 16px;
      height: 16px;
      fill: currentColor;
    }
    .read-at {
      color: var(--secondary-text-color);
      font-size: 0.8rem;
    }
    .version {
      margin-left: auto;
      color: var(--secondary-text-color);
      font-size: 0.75rem;
    }
    .reload {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-top: 12px;
      padding: 8px 12px;
      border-radius: 8px;
      background: var(--warning-color, #ffa600);
      color: var(--text-primary-color, #fff);
    }
    .reload button {
      cursor: pointer;
      border: none;
      border-radius: 6px;
      padding: 4px 12px;
      background: var(--primary-color, #03a9f4);
      color: var(--text-primary-color, #fff);
      font: inherit;
    }
    @media (max-width: 480px) {
      .range {
        gap: 6px;
      }
      .ranges,
      .errors,
      .note,
      .copy-panel {
        margin-left: 0;
      }
    }
  `;
__decorateClass([
  n2({ attribute: false })
], DanfossAllyScheduleCard.prototype, "hass", 2);
__decorateClass([
  r()
], DanfossAllyScheduleCard.prototype, "_config", 2);
__decorateClass([
  r()
], DanfossAllyScheduleCard.prototype, "_rooms", 2);
__decorateClass([
  r()
], DanfossAllyScheduleCard.prototype, "_info", 2);
__decorateClass([
  r()
], DanfossAllyScheduleCard.prototype, "_schedule", 2);
__decorateClass([
  r()
], DanfossAllyScheduleCard.prototype, "_loaded", 2);
__decorateClass([
  r()
], DanfossAllyScheduleCard.prototype, "_refreshing", 2);
__decorateClass([
  r()
], DanfossAllyScheduleCard.prototype, "_editing", 2);
__decorateClass([
  r()
], DanfossAllyScheduleCard.prototype, "_draft", 2);
__decorateClass([
  r()
], DanfossAllyScheduleCard.prototype, "_saving", 2);
__decorateClass([
  r()
], DanfossAllyScheduleCard.prototype, "_error", 2);
__decorateClass([
  r()
], DanfossAllyScheduleCard.prototype, "_job", 2);
__decorateClass([
  r()
], DanfossAllyScheduleCard.prototype, "_restoring", 2);
__decorateClass([
  r()
], DanfossAllyScheduleCard.prototype, "_copyFrom", 2);
__decorateClass([
  r()
], DanfossAllyScheduleCard.prototype, "_copyTargets", 2);
__decorateClass([
  r()
], DanfossAllyScheduleCard.prototype, "_serverValidation", 2);
DanfossAllyScheduleCard = __decorateClass([
  t$1("danfoss-ally-schedule-card")
], DanfossAllyScheduleCard);
const ICON_CHECK = w`<svg viewBox="0 0 24 24"><path d="M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.42z" /></svg>`;
const ICON_MINUS = w`<svg viewBox="0 0 24 24"><path d="M19 13H5v-2h14z" /></svg>`;
const ICON_ALERT = w`<svg viewBox="0 0 24 24"><path d="M13 14h-2V9h2m0 9h-2v-2h2M1 21h22L12 2z" /></svg>`;
const ICON_WRENCH = w`<svg viewBox="0 0 24 24"><path d="M22.7 19 13.6 9.9c.9-2.3.4-5-1.5-6.9-2-2-5-2.4-7.4-1.3L9 6 6 9 1.6 4.7C.4 7.1.9 10.1 2.9 12.1c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1c.4.4 1 .4 1.4 0l2.3-2.3c.5-.4.5-1.1.1-1.4z" /></svg>`;
const ICON_WIFI = w`<svg viewBox="0 0 24 24"><path d="M12 21 2 9c5.5-5 14.5-5 20 0zm0-3.5 3.5-4.2a5.3 5.3 0 0 0-7 0z" /></svg>`;
const ICON_WIFI_OFF = w`<svg viewBox="0 0 24 24"><path d="M2.3 4.3 1 5.6l2.3 2.3C2.8 8.3 2.4 8.6 2 9l10 12 3.3-4L18 19.7l1.3-1.4zM12 21ZM20.6 8.3A14 14 0 0 0 9.9 5.8l9.1 9.1 2.9-3.6c-.4-.3-.8-.7-1.3-1z" /></svg>`;
const ICON_REFRESH = w`<svg viewBox="0 0 24 24"><path d="M17.65 6.35A8 8 0 1 0 19.73 14h-2.08A6 6 0 1 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4z" /></svg>`;
const ICON_EDIT = w`<svg viewBox="0 0 24 24"><path d="M20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75M3 17.25V21h3.75L17.81 9.93l-3.75-3.75z" /></svg>`;
const ICON_SAVE = w`<svg viewBox="0 0 24 24"><path d="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7zm-5 16a3 3 0 1 1 0-6 3 3 0 0 1 0 6m3-10H5V5h10z" /></svg>`;
const ICON_PLUS = w`<svg viewBox="0 0 24 24"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z" /></svg>`;
const ICON_TRASH = w`<svg viewBox="0 0 24 24"><path d="M19 4h-3.5l-1-1h-5l-1 1H5v2h14zM6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6z" /></svg>`;
const ICON_COPY = w`<svg viewBox="0 0 24 24"><path d="M19 21H8V7h11m0-2H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2m-3-4H4a2 2 0 0 0-2 2v14h2V3h12z" /></svg>`;
const ICON_RESTORE = w`<svg viewBox="0 0 24 24"><path d="M13 3a9 9 0 0 0-9 9H1l4 4 4-4H6a7 7 0 1 1 7 7c-1.9 0-3.6-.8-4.9-2l-1.4 1.4A9 9 0 1 0 13 3m-1 5v5l4 2 .7-1.2-3.2-1.9V8z" /></svg>`;
const CARD_TYPE = "danfoss-ally-schedule-card";
window.customCards = window.customCards ?? [];
if (!window.customCards.some((card) => card.type === CARD_TYPE)) {
  window.customCards.push({
    type: CARD_TYPE,
    // Textes du sélecteur : le frontend HA n'est pas encore localisé pour cette
    // carte au lot 3 ; libellés bilingues courts en attendant le lot 4.
    name: "Danfoss Ally — Programme / Schedule",
    description: "Programme hebdomadaire d'une pièce Danfoss Ally (cloud). / Weekly schedule of a Danfoss Ally room.",
    preview: false,
    documentationURL: "https://github.com/aghulas/ha-danfoss-ally"
  });
}
console.info(
  `%c DANFOSS-ALLY-CLOUD %c ${CARD_VERSION} `,
  "color:#fff;background:#e2001a;font-weight:700",
  "color:#e2001a;background:#fff"
);
