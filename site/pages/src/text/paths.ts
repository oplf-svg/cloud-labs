import { LANGS, type Lang } from "./types.ts";

/** The address of a page in a language. English has no prefix. */
export const to = (lang: Lang, path = "/") => (lang === "en" ? path : `/${lang}${path}`);

/** One page per language, for getStaticPaths. */
export const everyLang = () => LANGS.map((lang) => ({ params: { lang: lang === "en" ? undefined : lang }, props: { lang } }));

export const day = (lang: Lang, date: string) => new Intl.DateTimeFormat(lang, { dateStyle: "long", timeZone: "UTC" }).format(new Date(date));
