import runs from "../../../packages/core/data/runs.json";
import type { Claim, Link } from "./types.ts";

const LABS = "https://github.com/oplf-svg/cloud-labs";
const file = (path: string) => `${LABS}/blob/main/${path}`;
const latest = runs.runs[runs.runs.length - 1]!;

const RUN: Link = { href: latest.url, text: { en: `Sign-in run ${latest.number}`, es: `Ejecución ${latest.number} del inicio de sesión`, fr: `Exécution ${latest.number} de la connexion` } };
const WORKFLOW: Link = { href: file(".github/workflows/sign-in.yml"), text: { en: "The workflow", es: "El workflow", fr: "Le workflow" } };
const SCRIPT: Link = { href: file("bootstrap/scripts/check_sign_in.py"), text: { en: "The test", es: "La prueba", fr: "Le test" } };
const RUN_TESTS: Link = { href: file("bootstrap/scripts/test_run.py"), text: { en: "Its tests", es: "Sus pruebas", fr: "Ses tests" } };
const NIGHT: Link = { href: `${LABS}/actions/workflows/nightly-destroy.yml`, text: { en: "The night runs", es: "Las ejecuciones nocturnas", fr: "Les exécutions de nuit" } };
const FILTER: Link = { href: file("site/scripts/import-runs.mjs"), text: { en: "The filter", es: "El filtro", fr: "Le filtre" } };
const tests = (path: string): Link => ({ href: file(path), text: { en: "The tests", es: "Las pruebas", fr: "Les tests" } });

export const CLAIMS: Claim[] = [
  {
    id: "no-keys", doors: ["cloud", "security"], project: "cloud-labs", status: "proven",
    claim: {
      en: "GitHub signs in to three clouds without a stored cloud key.",
      es: "GitHub inicia sesión en tres nubes sin ninguna clave de nube guardada.",
      fr: "GitHub se connecte à trois clouds sans aucune clé de cloud stockée.",
    },
    limit: {
      en: "Seen with one project, and on Google Cloud not yet with the identity that deploys. The other projects are set up, but have not signed in yet.",
      es: "Visto con un proyecto, y en Google Cloud todavía no con la identidad que despliega. Los demás proyectos están preparados, pero aún no han iniciado sesión.",
      fr: "Vu avec un projet, et sur Google Cloud pas encore avec l'identité qui déploie. Les autres projets sont prêts, mais ne se sont pas encore connectés.",
    },
    evidence: [RUN, NIGHT, WORKFLOW],
  },
  {
    id: "look-only", doors: ["cloud", "security", "agents"], project: "cloud-labs", status: "proven",
    claim: {
      en: "The read-only identity can look around in the clouds, but it cannot create anything or write state.",
      es: "La identidad de solo lectura puede mirar en las nubes, pero no puede crear nada ni escribir estado.",
      fr: "L'identité en lecture seule peut regarder dans les clouds, mais ne peut rien créer ni écrire d'état.",
    },
    limit: {
      en: "One kind of creation is tried on each cloud, not all of them.",
      es: "En cada nube se intenta un tipo de creación, no todos.",
      fr: "Un seul type de création est tenté sur chaque cloud, pas tous.",
    },
    evidence: [RUN, SCRIPT],
  },
  {
    id: "no-borrowing", doors: ["security", "cloud", "agents"], project: "cloud-labs", status: "proven",
    claim: {
      en: "The read-only identity cannot borrow the one that deploys.",
      es: "La identidad de solo lectura no puede tomar prestada la que despliega.",
      fr: "L'identité en lecture seule ne peut pas emprunter celle qui déploie.",
    },
    limit: {
      en: "Tried on AWS and on Google Cloud. On Azure it does not know the other identities, so it cannot even try.",
      es: "Intentado en AWS y en Google Cloud. En Azure no conoce las otras identidades, así que ni siquiera puede intentarlo.",
      fr: "Tenté sur AWS et sur Google Cloud. Sur Azure, elle ne connaît pas les autres identités, donc elle ne peut même pas essayer.",
    },
    evidence: [RUN, SCRIPT],
  },
  {
    id: "early-yes", doors: ["cloud", "leadership", "agents"], project: "cloud-labs", status: "proven",
    claim: {
      en: "A yes typed before the question is on the screen approves nothing.",
      es: "Un sí escrito antes de que la pregunta esté en pantalla no aprueba nada.",
      fr: "Un oui tapé avant que la question soit à l'écran n'approuve rien.",
    },
    evidence: [{ href: `${LABS}/pull/5`, text: { en: "Pull request 5", es: "Pull request 5", fr: "Pull request 5" } }, RUN_TESTS],
  },
  {
    id: "expected-plan", doors: ["cloud", "leadership"], project: "cloud-labs", status: "proven",
    claim: {
      en: "The setup stops before it creates anything if its plan has an unexpected size or would delete something.",
      es: "La preparación se detiene antes de crear nada si su plan tiene un tamaño inesperado o borraría algo.",
      fr: "La mise en place s'arrête avant de créer quoi que ce soit si son plan a une taille inattendue ou supprimerait quelque chose.",
    },
    evidence: [{ href: file("bootstrap/scripts/run.sh"), text: { en: "The script", es: "El script", fr: "Le script" } }, RUN_TESTS],
  },
  {
    id: "blocked-terms", doors: ["security", "leadership"], project: "cloud-labs", status: "proven",
    claim: {
      en: "Every pull request is searched for private terms, and its log never shows them.",
      es: "Cada pull request se revisa en busca de términos privados, y su registro nunca los muestra.",
      fr: "Chaque pull request est fouillée à la recherche de termes privés, et son journal ne les montre jamais.",
    },
    limit: {
      en: "It finds only the terms on a list, and a message typed into the merge box is not covered.",
      es: "Solo encuentra los términos de una lista, y no cubre un mensaje escrito en el cuadro de fusión.",
      fr: "Il ne trouve que les termes d'une liste, et ne couvre pas un message tapé dans la fenêtre de fusion.",
    },
    evidence: [
      { href: file(".github/scripts/blocked_terms.py"), text: { en: "The check", es: "La comprobación", fr: "Le contrôle" } },
      { href: file(".github/scripts/test_blocked_terms.py"), text: { en: "Its tests", es: "Sus pruebas", fr: "Ses tests" } },
    ],
  },
  {
    id: "two-builds", doors: ["frontend"], project: "cloud-labs", status: "proven",
    claim: {
      en: "The recorder behaves the same in React and in Angular, with a keyboard, with less motion and in three languages.",
      es: "El registrador se comporta igual en React y en Angular, con teclado, con menos movimiento y en tres idiomas.",
      fr: "L'enregistreur se comporte de la même façon en React et en Angular, au clavier, avec moins de mouvement et en trois langues.",
    },
    evidence: [tests("site/e2e/recorder.spec.ts")],
  },
  {
    id: "log-words", doors: ["agents", "security"], project: "cloud-labs", status: "proven",
    claim: {
      en: "Nothing written into a log can become text on this site, unless it is one of the test's own sentences.",
      es: "Nada escrito en un registro puede convertirse en texto de este sitio, salvo que sea una de las frases de la propia prueba.",
      fr: "Rien de ce qui est écrit dans un journal ne peut devenir du texte sur ce site, sauf une des phrases du test lui-même.",
    },
    evidence: [FILTER, tests("site/scripts/import-runs.test.mjs")],
  },
  {
    id: "same-for-machines", doors: ["agents", "frontend"], project: "cloud-labs", status: "proven",
    claim: {
      en: "What a machine reads on this site is what a person can see: no hidden text, no invisible characters, nothing from elsewhere.",
      es: "Lo que una máquina lee en este sitio es lo que una persona puede ver: sin texto oculto, sin caracteres invisibles, nada de otros sitios.",
      fr: "Ce qu'une machine lit sur ce site est ce qu'une personne peut voir : pas de texte caché, pas de caractères invisibles, rien qui vienne d'ailleurs.",
    },
    evidence: [tests("site/e2e/pages.spec.ts")],
  },
  {
    id: "pinned", doors: ["agents", "security"], project: "cloud-labs", status: "proven",
    claim: {
      en: "Every package this site is built from is pinned, has a fingerprint, and cannot run anything while it is installed.",
      es: "Cada paquete con el que se construye este sitio está fijado, tiene una huella y no puede ejecutar nada al instalarse.",
      fr: "Chaque paquet dont ce site est construit est figé, a une empreinte, et ne peut rien exécuter pendant son installation.",
    },
    evidence: [tests("site/scripts/packages.test.mjs")],
  },
  {
    id: "once", doors: ["backend", "data"], project: "webhook-platform", status: "planned",
    claim: {
      en: "No event is lost or handled twice, and forged ones are refused.",
      es: "Ningún evento se pierde ni se procesa dos veces, y los falsificados se rechazan.",
      fr: "Aucun événement n'est perdu ni traité deux fois, et les faux sont refusés.",
    },
    evidence: [],
  },
  {
    id: "last-item", doors: ["backend"], project: "webhook-platform", status: "planned",
    claim: {
      en: "The last item in stock sells exactly once, even through two channels at the same moment.",
      es: "El último artículo se vende exactamente una vez, aunque lo pidan dos canales en el mismo momento.",
      fr: "Le dernier article en stock se vend exactement une fois, même par deux canaux au même moment.",
    },
    evidence: [],
  },
  {
    id: "tenants", doors: ["backend", "security"], project: "webhook-platform", status: "planned",
    claim: {
      en: "One customer can never reach another customer's data, through any request, job or callback.",
      es: "Un cliente nunca puede llegar a los datos de otro, por ninguna petición, tarea o callback.",
      fr: "Un client ne peut jamais atteindre les données d'un autre, par aucune requête, tâche ou callback.",
    },
    evidence: [],
  },
  {
    id: "kill-switch", doors: ["backend", "leadership"], project: "webhook-platform", status: "planned",
    claim: {
      en: "When a provider changes its format without notice, that feed is cut off and the rest keeps working.",
      es: "Cuando un proveedor cambia su formato sin avisar, se corta esa entrada y el resto sigue funcionando.",
      fr: "Quand un fournisseur change son format sans prévenir, ce flux est coupé et le reste continue de fonctionner.",
    },
    evidence: [],
  },
  {
    id: "signed", doors: ["backend", "security"], project: "webhook-platform", status: "planned",
    claim: {
      en: "A document that was changed after it was signed is refused.",
      es: "Un documento cambiado después de firmarse se rechaza.",
      fr: "Un document modifié après sa signature est refusé.",
    },
    evidence: [],
  },
  {
    id: "reconcile", doors: ["data"], project: "event-pipeline-lab", status: "planned",
    claim: {
      en: "Every total can be traced back to raw events, and bad records are set aside and counted.",
      es: "Cada total se puede seguir hasta los eventos de origen, y los registros malos se apartan y se cuentan.",
      fr: "Chaque total peut être suivi jusqu'aux événements bruts, et les mauvais enregistrements sont mis de côté et comptés.",
    },
    evidence: [],
  },
  {
    id: "does-not-know", doors: ["ai", "data"], project: "ai-ops-agent", status: "planned",
    claim: {
      en: "The assistant answers from checked data, or says that it doesn't know.",
      es: "El asistente responde con datos verificados, o dice que no sabe.",
      fr: "L'assistant répond à partir de données vérifiées, ou dit qu'il ne sait pas.",
    },
    evidence: [],
  },
  {
    id: "names-the-cause", doors: ["ai", "leadership", "agents"], project: "ai-ops-agent", status: "planned",
    claim: {
      en: "The agent names the cause of a staged failure, its misses are published, and it cannot act without approval.",
      es: "El agente nombra la causa de una falla preparada, sus errores se publican, y no puede actuar sin aprobación.",
      fr: "L'agent nomme la cause d'une panne mise en scène, ses erreurs sont publiées, et il ne peut pas agir sans approbation.",
    },
    evidence: [],
  },
  {
    id: "rollback", doors: ["cloud"], project: "k8s-platform-lab", status: "planned",
    claim: {
      en: "A bad release rolls itself back, and the errors that users saw are counted.",
      es: "Una mala versión se revierte sola, y se cuentan los errores que vieron los usuarios.",
      fr: "Une mauvaise version est annulée d'elle-même, et les erreurs vues par les utilisateurs sont comptées.",
    },
    evidence: [],
  },
  {
    id: "nothing-left", doors: ["cloud", "leadership"], project: "cloud-labs", status: "planned",
    claim: {
      en: "Nothing is left running at night, and what was spent is published.",
      es: "Nada queda encendido por la noche, y se publica lo gastado.",
      fr: "Rien ne reste allumé la nuit, et ce qui a été dépensé est publié.",
    },
    limit: {
      en: "This site stays on, on plans that cost nothing.",
      es: "Este sitio sigue encendido, con planes que no cuestan nada.",
      fr: "Ce site reste en ligne, avec des offres qui ne coûtent rien.",
    },
    evidence: [],
  },
  {
    id: "own-identity", doors: ["agents", "security", "leadership"], project: "cloud-labs", status: "planned",
    claim: {
      en: "An agent works under its own identity, which cannot approve, merge or change a rule.",
      es: "Un agente trabaja con su propia identidad, que no puede aprobar, fusionar ni cambiar una regla.",
      fr: "Un agent travaille sous sa propre identité, qui ne peut ni approuver, ni fusionner, ni changer une règle.",
    },
    evidence: [],
  },
  {
    id: "planted", doors: ["agents", "ai"], project: "ai-ops-agent", status: "planned",
    claim: {
      en: "An instruction planted in a message, a log or a comment is never followed, even when many of them agree.",
      es: "Una instrucción plantada en un mensaje, un registro o un comentario nunca se sigue, aunque muchas coincidan.",
      fr: "Une instruction glissée dans un message, un journal ou un commentaire n'est jamais suivie, même si beaucoup concordent.",
    },
    evidence: [],
  },
  {
    id: "together", doors: ["agents", "backend"], project: "webhook-platform", status: "planned",
    claim: {
      en: "Many callers that each stay under their own limit cannot together pass the limit for all.",
      es: "Muchos clientes que respetan cada uno su límite no pueden superar juntos el límite de todos.",
      fr: "Beaucoup d'appelants qui respectent chacun leur limite ne peuvent pas ensemble dépasser la limite commune.",
    },
    evidence: [],
  },
  {
    id: "one-switch", doors: ["agents", "cloud", "leadership"], project: "cloud-labs", status: "planned",
    claim: {
      en: "One switch takes every right away from every agent, and no agent can turn it back on.",
      es: "Un interruptor quita todos los permisos a todos los agentes, y ningún agente puede volver a encenderlos.",
      fr: "Un seul interrupteur retire tous les droits à tous les agents, et aucun agent ne peut les rétablir.",
    },
    evidence: [],
  },
  {
    id: "no-runaway-bill", doors: ["agents", "cloud"], project: "cloud-labs", status: "planned",
    claim: {
      en: "However many attackers come, they cannot run up a bill: the site is on plans that stop instead of charging.",
      es: "Por muchos atacantes que vengan, no pueden disparar la factura: el sitio usa planes que se detienen en lugar de cobrar.",
      fr: "Aussi nombreux que soient les attaquants, ils ne peuvent pas faire exploser la facture : le site utilise des offres qui s'arrêtent au lieu de facturer.",
    },
    evidence: [],
  },
  {
    id: "rehearsed", doors: ["agents", "security", "leadership"], project: "webhook-platform", status: "planned",
    claim: {
      en: "A group of attacking agents is set on this system in public, and what gets through is published.",
      es: "Se lanza en público un grupo de agentes atacantes contra este sistema, y lo que logra pasar se publica.",
      fr: "Un groupe d'agents attaquants est lâché en public sur ce système, et ce qui passe est publié.",
    },
    evidence: [],
  },
];
