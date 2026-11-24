import runs from "../../../packages/core/data/runs.json";
import type { Note } from "./types.ts";

const LABS = "https://github.com/oplf-svg/cloud-labs";
const pull = (n: number) => ({ href: `${LABS}/pull/${n}`, text: { en: `Pull request ${n}`, es: `Pull request ${n}`, fr: `Pull request ${n}` } });
const run = (n: number) => ({ href: runs.runs.find((known) => known.number === n)!.url, text: { en: `Sign-in run ${n}`, es: `Ejecución ${n}`, fr: `Exécution ${n}` } });

export const NOTES: Note[] = [
  {
    slug: "the-check-that-proved-nothing",
    date: "2026-11-24",
    title: { en: "The check that proved nothing", es: "La comprobación que no probaba nada", fr: "Le contrôle qui ne prouvait rien" },
    summary: {
      en: "One check was red and wrong. The green one above it was worse.",
      es: "Una comprobación estaba en rojo y equivocada. La verde de arriba era peor.",
      fr: "Un contrôle était rouge et se trompait. Le vert juste au-dessus était pire.",
    },
    happened: [
      {
        en: "The first real sign-in test had one red line. It said that this project could read another project's state on AWS. It couldn't: the test had asked for a file that doesn't exist, and S3 tells everyone who may list a bucket that a file is missing, whatever they may open.",
        es: "La primera prueba real de inicio de sesión tuvo una línea roja. Decía que este proyecto podía leer el estado de otro en AWS. No podía: la prueba había pedido un archivo que no existe, y S3 le dice a todo el que puede listar un bucket que un archivo falta, sin importar lo que pueda abrir.",
        fr: "Le premier vrai test de connexion avait une ligne rouge. Il disait que ce projet pouvait lire l'état d'un autre sur AWS. C'était faux : le test avait demandé un fichier qui n'existe pas, et S3 dit à tous ceux qui peuvent lister un bucket qu'un fichier manque, quoi qu'ils puissent ouvrir.",
      },
    ],
    silent: {
      en: "The red line was easy to find. But “read its own state: allowed” had passed for exactly the same reason, so it had proved nothing. A check that passes for the wrong reason looks like every other green line.",
      es: "La línea roja era fácil de encontrar. Pero «leer su propio estado: permitido» había pasado por la misma razón, así que no había probado nada. Una comprobación que pasa por la razón equivocada se ve como cualquier otra línea verde.",
      fr: "La ligne rouge était facile à trouver. Mais « lire son propre état : autorisé » était passé pour exactement la même raison, et n'avait donc rien prouvé. Un contrôle qui passe pour la mauvaise raison ressemble à n'importe quelle autre ligne verte.",
    },
    now: {
      en: "The test now opens a file that it has found in the list. If there is none, it says “nothing there” instead of claiming a result.",
      es: "La prueba abre ahora un archivo que ha encontrado en la lista. Si no hay ninguno, dice «nada que abrir» en lugar de afirmar un resultado.",
      fr: "Le test ouvre maintenant un fichier trouvé dans la liste. S'il n'y en a pas, il dit « rien à ouvrir » au lieu d'affirmer un résultat.",
    },
    evidence: [run(1), run(2), pull(4)],
  },
  {
    slug: "the-yes-that-came-too-early",
    date: "2026-11-24",
    title: { en: "The yes that came too early", es: "El sí que llegó demasiado pronto", fr: "Le oui arrivé trop tôt" },
    summary: {
      en: "A second yes to one question could approve the next, before it was on the screen.",
      es: "Un segundo sí a una pregunta podía aprobar la siguiente, antes de que estuviera en pantalla.",
      fr: "Un deuxième oui à une question pouvait approuver la suivante, avant qu'elle soit à l'écran.",
    },
    happened: [
      {
        en: "A setup script shows its plan and then asks for a yes. While it was still working, I typed something extra. The terminal kept it and handed it to the next question as the answer. An extra Enter stopped one run, and half a word stopped another.",
        es: "Un script de preparación muestra su plan y luego pide un sí. Mientras todavía trabajaba, escribí algo de más. La terminal lo guardó y se lo dio a la siguiente pregunta como respuesta. Un Enter de más detuvo una ejecución, y media palabra detuvo otra.",
        fr: "Un script de mise en place montre son plan puis demande un oui. Pendant qu'il travaillait encore, j'ai tapé quelque chose de trop. Le terminal l'a gardé et l'a donné à la question suivante comme réponse. Une touche Entrée de trop a arrêté une exécution, et un demi-mot une autre.",
      },
      {
        en: "Both stops were luck. Tests showed that a clean early yes did approve the plan.",
        es: "Las dos veces fue suerte que se detuviera. Las pruebas mostraron que un sí limpio y temprano sí aprobaba el plan.",
        fr: "Les deux arrêts étaient de la chance. Des tests ont montré qu'un oui net et trop tôt approuvait bien le plan.",
      },
    ],
    silent: {
      en: "The record would have shown a plan and an approval. Nothing in it says that nobody had read the plan.",
      es: "El registro habría mostrado un plan y una aprobación. Nada en él dice que nadie había leído el plan.",
      fr: "La trace aurait montré un plan et une approbation. Rien n'y dit que personne n'avait lu le plan.",
    },
    now: {
      en: "Every question first throws away what was typed before it. Tests type early at a simulated terminal: a yes, a second yes, an extra Enter, half a word. All of them fail on the old script.",
      es: "Cada pregunta descarta primero lo que se escribió antes. Las pruebas escriben antes de tiempo en una terminal simulada: un sí, un segundo sí, un Enter de más, media palabra. Todas fallan con el script anterior.",
      fr: "Chaque question jette d'abord ce qui a été tapé avant elle. Des tests tapent trop tôt dans un terminal simulé : un oui, un deuxième oui, une touche Entrée de trop, un demi-mot. Tous échouent avec l'ancien script.",
    },
    evidence: [pull(5)],
  },
  {
    slug: "the-refusal-that-looked-like-nothing",
    date: "2026-11-24",
    title: { en: "The refusal that looked like nothing", es: "La negativa que parecía nada", fr: "Le refus qui ressemblait à rien" },
    summary: {
      en: "“You may not ask” was read as “there is none”.",
      es: "«No puedes preguntar» se leyó como «no hay ninguno».",
      fr: "« Vous n'avez pas le droit de demander » a été lu comme « il n'y en a pas ».",
    },
    happened: [
      {
        en: "Before it creates anything, the setup script asks AWS whether the account already trusts GitHub. A new kind of account isn't allowed to ask. The script searched the answer for GitHub, found nothing, and went on.",
        es: "Antes de crear nada, el script de preparación pregunta a AWS si la cuenta ya confía en GitHub. Un nuevo tipo de cuenta no tiene permiso para preguntarlo. El script buscó GitHub en la respuesta, no encontró nada y siguió.",
        fr: "Avant de créer quoi que ce soit, le script de mise en place demande à AWS si le compte fait déjà confiance à GitHub. Un nouveau type de compte n'a pas le droit de le demander. Le script a cherché GitHub dans la réponse, n'a rien trouvé et a continué.",
      },
    ],
    silent: {
      en: "An error and an empty list looked the same to it. It would have stopped halfway through creating 104 resources.",
      es: "Para él, un error y una lista vacía eran lo mismo. Se habría detenido a mitad de la creación de 104 recursos.",
      fr: "Pour lui, une erreur et une liste vide étaient la même chose. Il se serait arrêté au milieu de la création de 104 ressources.",
    },
    now: {
      en: "A refusal stops the run before anything is created, and so does a region the account may not use. Stand-ins for AWS test both.",
      es: "Una negativa detiene la ejecución antes de crear nada, y también una región que la cuenta no puede usar. Sustitutos de AWS prueban ambos casos.",
      fr: "Un refus arrête l'exécution avant toute création, de même qu'une région que le compte ne peut pas utiliser. Des doublures d'AWS testent les deux cas.",
    },
    evidence: [pull(3)],
  },
];
