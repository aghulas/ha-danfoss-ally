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
    degree: "{value} °C"
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
    degree: "{value} °C"
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
const CARD_VERSION = "0.1.0";
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
    this._config = config;
  }
  getCardSize() {
    return 6;
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
  render() {
    const room = pickRoom(this._rooms, this._config?.room_id);
    const showReload = needsReload(CARD_VERSION, this._info?.version);
    const readOnly = this._info !== null && !this._info.is_admin;
    return b`
      <ha-card>
        <div class="content">
          ${showReload ? this._renderReloadBanner() : A}
          <div class="room">${this._roomTitle(room)}</div>
          ${readOnly ? b`<div class="hint">${t(this.hass, "read_only")}</div>` : A}
          ${this._renderBody(room)}
        </div>
      </ha-card>
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
      ${schedule ? this._renderGrid(schedule) : b`<div class="hint">${t(this.hass, "schedule_unavailable")}</div>`}
      ${this._renderHeads(room)}
      ${this._renderFooter(schedule)}
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
  _renderGrid(schedule) {
    return b`
      <div class="grid">
        <div class="scale" aria-hidden="true">
          <span>0 h</span><span>6 h</span><span>12 h</span><span>18 h</span><span>24 h</span>
        </div>
        ${DAY_KEYS.map((day) => this._renderDay(day, schedule.days[day] ?? []))}
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
    const parts = bars.map(
      (bar) => t(this.hass, "range_label", { start: bar.start, end: bar.end })
    );
    return `${name} — ${parts.join(", ")}`;
  }
  _renderHeads(room) {
    const heads = room?.heads ?? [];
    return b`
      <div class="heads">
        <div class="heads-title">${t(this.hass, "heads_heading")}</div>
        ${heads.length === 0 ? b`<div class="hint">${t(this.hass, "heads_none")}</div>` : b`<div class="heads-list">
              ${heads.map((head) => this._renderHead(head))}
            </div>`}
      </div>
    `;
  }
  _renderHead(head) {
    return b`
      <div class="head">
        <span class="head-name">${head.name}</span>
        <span class="badges">
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
  _badge(kind, icon, label) {
    return b`
      <span class="badge ${kind}" title=${label} role="img" aria-label=${label}>${icon}</span>
    `;
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
    .room {
      font-size: 1.4rem;
      font-weight: 500;
      color: var(--primary-text-color);
      padding-top: 16px;
    }
    .hint {
      margin-top: 8px;
      color: var(--secondary-text-color);
      font-size: 0.9rem;
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
    .bar {
      position: absolute;
      top: 0;
      bottom: 0;
      border-radius: 3px;
      min-width: 2px;
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
