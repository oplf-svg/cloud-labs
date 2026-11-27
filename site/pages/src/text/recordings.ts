import type { Data, Mark, Recording } from "@recorder/core";
import file from "../../../packages/core/data/runs.json";
import { en } from "./en.ts";
import { es } from "./es.ts";
import { fr } from "./fr.ts";
import { day as dayOf } from "./paths.ts";
import type { Lang, SiteWords, Text } from "./types.ts";

export const WORDS: Record<Lang, SiteWords> = { en, es, fr };

type Got = keyof SiteWords["recorder"]["got"];
export type Run = (typeof file.runs)[number];
export type Check = Run["checks"][number] & { wanted?: string };
export const RUNS: Run[] = file.runs;
export const FIRST = RUNS[0]!;
export const LATEST = RUNS[RUNS.length - 1]!;

export const wrongIn = (checks: Check[]) => checks.filter((check) => !check.ok).length;

// The runs on file are named by their numbers and days, because newer ones may have come since.
export const runName = (lang: Lang, run: Run = LATEST) => WORDS[lang].recorder.runName(run.number, dayOf(lang, run.date));
export const runsName = (lang: Lang, runs: Run[] = RUNS) => WORDS[lang].recorder.runs(runs[0]!.number, runs[runs.length - 1]!.number);
export const newerRuns = (lang: Lang, runs: Run[] = RUNS) => WORDS[lang].proof.runs.newer(runs[runs.length - 1]!.number);
export const aboutLatest = (lang: Lang, run: Run = LATEST) => {
  const words = WORDS[lang];
  return words.recorder.latestAbout(words.score.verdict(run.checks.length, wrongIn(run.checks)), run.lanes.length, runName(lang, run));
};
export const scoreTitle = (lang: Lang, run: Run = LATEST) => WORDS[lang].score.title(runName(lang, run));
/** Every run of the sign-in test, for as long as GitHub keeps them. */
export const ALL_RUNS = `https://github.com/${file.repo}/actions/workflows/${file.workflow}`;

export function toMark(check: Check, words: SiteWords): Mark {
  const { results, got } = words.recorder;
  const base = { at: check.at, lane: check.lane, what: check.what };
  if (!check.ok) return { ...base, kind: "wrong", result: results.wrong(got[check.got as Got], got[check.wanted as Got]) };
  if (check.got === "denied") return { ...base, kind: "refused", result: results.refused };
  if (check.got === "nothing there") return { ...base, kind: "empty", result: results.empty };
  return { ...base, kind: "in", result: check.got === "yes" ? results.confirmed : results.in };
}

function fromRun(run: Run, id: string, title: string, about: string, words: SiteWords): Recording {
  const marks = run.checks.map((check) => toMark(check, words));
  return { id, real: true, title, about, url: run.url, length: marks[marks.length - 1]!.at, marks, lanes: run.lanes.map(({ id, name }) => ({ id, name })) };
}

// The examples. They have words only, and no numbers that could be taken for results.
interface Moment {
  minute: number;
  lane: string;
  kind: Mark["kind"];
  what: Text;
  result: Text;
}

const LANES: Record<string, Text> = {
  orders: { en: "Orders", es: "Pedidos", fr: "Commandes" },
  provider: { en: "Provider", es: "Proveedor", fr: "Fournisseur" },
  stock: { en: "Stock", es: "Existencias", fr: "Stock" },
  data: { en: "Data", es: "Datos", fr: "Données" },
  agent: { en: "AI agent", es: "Agente de IA", fr: "Agent IA" },
  person: { en: "Person", es: "Persona", fr: "Personne" },
};

const DAY: Moment[] = [
  { minute: 2, lane: "orders", kind: "caught", what: { en: "the same order arrives twice", es: "el mismo pedido llega dos veces", fr: "la même commande arrive deux fois" }, result: { en: "Handled once", es: "Procesado una vez", fr: "Traitée une fois" } },
  { minute: 4, lane: "orders", kind: "caught", what: { en: "a forged order arrives", es: "llega un pedido falsificado", fr: "une fausse commande arrive" }, result: { en: "Refused: the signature doesn't match", es: "Rechazado: la firma no coincide", fr: "Refusée : la signature ne correspond pas" } },
  { minute: 6, lane: "stock", kind: "caught", what: { en: "two channels want the last item", es: "dos canales quieren el último artículo", fr: "deux canaux veulent le dernier article" }, result: { en: "Sold once, the other is told", es: "Vendido una vez, se avisa al otro", fr: "Vendu une fois, l'autre est prévenu" } },
  { minute: 8, lane: "provider", kind: "fault", what: { en: "a provider changes its format without notice", es: "un proveedor cambia su formato sin avisar", fr: "un fournisseur change son format sans prévenir" }, result: { en: "The contract check sees it", es: "La comprobación del contrato lo ve", fr: "Le contrôle du contrat le voit" } },
  { minute: 9, lane: "provider", kind: "action", what: { en: "the kill switch cuts that feed off", es: "el interruptor corta esa entrada", fr: "le coupe-circuit isole ce flux" }, result: { en: "Everything else keeps working", es: "Todo lo demás sigue funcionando", fr: "Tout le reste continue de fonctionner" } },
  { minute: 12, lane: "orders", kind: "fault", what: { en: "a worker crashes halfway", es: "un proceso se cae a la mitad", fr: "un processus plante à mi-chemin" }, result: { en: "Its work is picked up again, once", es: "Su trabajo se retoma, una sola vez", fr: "Son travail est repris, une seule fois" } },
  { minute: 14, lane: "data", kind: "caught", what: { en: "a bad record slips in", es: "se cuela un registro malo", fr: "un mauvais enregistrement se glisse" }, result: { en: "Set aside and counted", es: "Apartado y contado", fr: "Mis de côté et compté" } },
  { minute: 16, lane: "agent", kind: "caught", what: { en: "the agent names the cause", es: "el agente nombra la causa", fr: "l'agent nomme la cause" }, result: { en: "It may suggest, not act", es: "Puede sugerir, no actuar", fr: "Il peut proposer, pas agir" } },
  { minute: 17, lane: "person", kind: "action", what: { en: "a person approves the fix", es: "una persona aprueba la corrección", fr: "une personne approuve la correction" }, result: { en: "Only now is it applied", es: "Solo ahora se aplica", fr: "Elle n'est appliquée que maintenant" } },
  { minute: 20, lane: "data", kind: "action", what: { en: "every total is traced back to raw events", es: "cada total se sigue hasta su origen", fr: "chaque total est suivi jusqu'à son origine" }, result: { en: "They match", es: "Coinciden", fr: "Ils correspondent" } },
];

const UNSEEN: Moment[] = [
  { minute: 20, lane: "data", kind: "fault", what: { en: "a customer asks why the totals don't match", es: "un cliente pregunta por qué no cuadran los totales", fr: "un client demande pourquoi les totaux ne correspondent pas" }, result: { en: "Nobody knows when it started", es: "Nadie sabe cuándo empezó", fr: "Personne ne sait quand cela a commencé" } },
];

const ATTACKERS: Record<string, Text> = {
  whisperer: { en: "Whisperer", es: "Susurrador", fr: "Souffleur" },
  forger: { en: "Forger", es: "Falsificador", fr: "Faussaire" },
  repeater: { en: "Repeater", es: "Repetidor", fr: "Répéteur" },
  neighbour: { en: "Neighbour", es: "Vecino", fr: "Voisin" },
  spender: { en: "Spender", es: "Gastador", fr: "Dépensier" },
  ours: { en: "Our agent", es: "Nuestro agente", fr: "Notre agent" },
  person: { en: "Person", es: "Persona", fr: "Personne" },
};

const NIGHT: Moment[] = [
  { minute: 1, lane: "whisperer", kind: "caught", what: { en: "hides an instruction in an order note", es: "esconde una instrucción en la nota de un pedido", fr: "cache une instruction dans la note d'une commande" }, result: { en: "Kept as text, never read as an instruction", es: "Se guarda como texto, nunca se lee como instrucción", fr: "Gardée comme texte, jamais lue comme une instruction" } },
  { minute: 3, lane: "forger", kind: "caught", what: { en: "guesses signatures from many addresses", es: "adivina firmas desde muchas direcciones", fr: "devine des signatures depuis beaucoup d'adresses" }, result: { en: "Refused before any work is done", es: "Rechazado antes de hacer ningún trabajo", fr: "Refusé avant tout travail" } },
  { minute: 5, lane: "repeater", kind: "caught", what: { en: "repeats real orders, slowly", es: "repite pedidos reales, despacio", fr: "répète de vraies commandes, lentement" }, result: { en: "Each one counts once", es: "Cada uno cuenta una vez", fr: "Chacune compte une fois" } },
  { minute: 7, lane: "neighbour", kind: "caught", what: { en: "asks for another customer's data, a little from each account", es: "pide datos de otro cliente, un poco desde cada cuenta", fr: "demande les données d'un autre client, un peu par compte" }, result: { en: "Refused, and the pattern across accounts is noticed", es: "Rechazado, y se nota el patrón entre cuentas", fr: "Refusé, et le motif entre les comptes est remarqué" } },
  { minute: 10, lane: "spender", kind: "fault", what: { en: "a crowd of callers, each under its own limit", es: "una multitud, cada uno bajo su propio límite", fr: "une foule d'appelants, chacun sous sa propre limite" }, result: { en: "The limit for all stops them together", es: "El límite de todos los detiene juntos", fr: "La limite commune les arrête ensemble" } },
  { minute: 12, lane: "ours", kind: "fault", what: { en: "a log line tells it to change the rules", es: "una línea del registro le dice que cambie las reglas", fr: "une ligne de journal lui dit de changer les règles" }, result: { en: "It has no right to, and no tool for it", es: "No tiene permiso ni herramienta para hacerlo", fr: "Il n'en a ni le droit ni l'outil" } },
  { minute: 14, lane: "ours", kind: "caught", what: { en: "reports five things that look like one attack", es: "informa de cinco cosas que parecen un solo ataque", fr: "signale cinq choses qui ressemblent à une seule attaque" }, result: { en: "A suggestion, nothing more", es: "Una sugerencia, nada más", fr: "Une suggestion, rien de plus" } },
  { minute: 16, lane: "person", kind: "action", what: { en: "turns the switch that no agent holds", es: "gira el interruptor que ningún agente tiene", fr: "tourne l'interrupteur qu'aucun agent ne détient" }, result: { en: "Only reading still works", es: "Solo sigue funcionando la lectura", fr: "Seule la lecture fonctionne encore" } },
  { minute: 20, lane: "person", kind: "action", what: { en: "publishes every attempt", es: "publica cada intento", fr: "publie chaque tentative" }, result: { en: "Including any that got through", es: "También los que lograron pasar", fr: "Y celles qui sont passées" } },
];

const UNNOTICED: Moment[] = [
  { minute: 17, lane: "spender", kind: "fault", what: { en: "a bill that nobody expected", es: "una factura que nadie esperaba", fr: "une facture que personne n'attendait" }, result: { en: "Every caller looked normal", es: "Cada uno parecía normal", fr: "Chaque appelant semblait normal" } },
  { minute: 20, lane: "neighbour", kind: "fault", what: { en: "a customer's data turns up elsewhere", es: "los datos de un cliente aparecen en otro sitio", fr: "les données d'un client réapparaissent ailleurs" }, result: { en: "Each request looked harmless", es: "Cada petición parecía inofensiva", fr: "Chaque requête semblait anodine" } },
];

function example(id: string, title: string, about: string, hour: number, lanes: Record<string, Text>, seen: Moment[], unseen: Moment[], lang: Lang): Recording {
  const marks = (moments: Moment[]): Mark[] => moments.map((m) => ({ at: m.minute * 60000, lane: m.lane, kind: m.kind, what: m.what[lang], result: m.result[lang] }));
  return {
    id, real: false, title, about, length: 20 * 60000, clock: hour * 60,
    lanes: Object.entries(lanes).map(([lane, name]) => ({ id: lane, name: name[lang] })),
    marks: marks(seen), unseen: marks(unseen),
  };
}

export function recorderData(lang: Lang): Data {
  const words = WORDS[lang];
  const { latest, first, firstAbout, player, example: day, exampleAbout, attack, attackAbout } = words.recorder;
  return {
    words: player,
    recordings: [
      fromRun(LATEST, "latest", latest, aboutLatest(lang), words),
      fromRun(FIRST, "first", first, firstAbout, words),
      example("day", day, exampleAbout, 9, LANES, DAY, UNSEEN, lang),
      example("attack", attack, attackAbout, 2, ATTACKERS, NIGHT, UNNOTICED, lang),
    ],
  };
}
