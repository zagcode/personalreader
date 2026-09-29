"use strict";

/* Tradução da interface.
   Os textos ficam em /static/locales/<idioma>.json. pt-BR é o padrão e a
   referência: uma chave que faltar em outro idioma cai no texto em português.
   No HTML:
     data-i18n="chave"           troca o texto do elemento
     data-i18n-label="chave"     troca aria-label (e title, com data-shortcut)
     data-shortcut="←"           atalho mostrado no title; "@chave" traduz o atalho */

const I18N = {
  // Nomes no próprio idioma: quem não entende a interface atual ainda acha o seu.
  locales: { "pt-BR": "Português", en: "English", es: "Español" },
  fallback: "pt-BR",
  current: "pt-BR",
  dict: {},
  base: {},
};

async function loadLocale(code) {
  if (!(code in I18N.locales)) code = I18N.fallback;
  const build = document.querySelector('meta[name="build"]')?.content || "";
  const get = async (c) => (await fetch(`/static/locales/${c}.json?v=${build}`)).json();
  if (!Object.keys(I18N.base).length) I18N.base = await get(I18N.fallback);
  I18N.dict = code === I18N.fallback ? I18N.base : await get(code);
  I18N.current = code;
  document.documentElement.lang = code;
}

function t(key, params = {}) {
  const text = I18N.dict[key] ?? I18N.base[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (match, name) => (name in params ? String(params[name]) : match));
}

function applyI18n(root = document) {
  root.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  root.querySelectorAll("[data-i18n-label]").forEach((el) => {
    const label = t(el.dataset.i18nLabel);
    el.setAttribute("aria-label", label);
    const shortcut = el.dataset.shortcut;
    if (shortcut) el.title = `${label} (${shortcut.startsWith("@") ? t(shortcut.slice(1)) : shortcut})`;
  });
}

/* 0,85 em português e espanhol; 0.85 em inglês. */
function fmtNumber(n) {
  return new Intl.NumberFormat(I18N.current).format(n);
}

/* "pt-BR" -> "Português (Brasil)" / "Portuguese (Brazil)" / "Portugués (Brasil)". */
function languageName(tag) {
  try {
    const name = new Intl.DisplayNames([I18N.current], { type: "language" }).of(tag);
    return name.charAt(0).toLocaleUpperCase(I18N.current) + name.slice(1);
  } catch {
    return tag;
  }
}

/* Erro da API ou do documento: {code, params} vira texto no idioma atual.
   Documentos antigos guardam o erro como texto pronto, que passa direto. */
function errorText(error, status) {
  if (error && typeof error === "object" && error.code) {
    const params = { ...error.params };
    if (error.code === "unsupported_format" && !params.ext) params.ext = t("error.noExtension");
    return t(`error.${error.code}`, params);
  }
  if (typeof error === "string" && error) return error;
  return t("error.http", { status: status ?? "?" });
}
