import { LANGS, type Lang } from "./types.ts";

/** The address of a page in a language. English has no prefix. */
export const to = (lang: Lang, path = "/") => (lang === "en" ? path : `/${lang}${path}`);

/** One page per language, for getStaticPaths. */
export const everyLang = () => LANGS.map((lang) => ({ params: { lang: lang === "en" ? undefined : lang }, props: { lang } }));

/** The day of a moment, in UTC wherever it is built, as each language writes it: French writes the first of a month as 1er. */
export const day = (lang: Lang, date: string) => {
  const said = new Intl.DateTimeFormat(lang, { dateStyle: "long", timeZone: "UTC" }).format(new Date(date));
  return lang === "fr" ? said.replace(/^1 /, "1er ") : said;
};
