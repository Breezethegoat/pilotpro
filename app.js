/* PilotPro mobile : écrans du téléphone. Les calculs et les écritures sont faits par le moteur
   (le même code Python que sur l'ordinateur), qui tourne dans moteur.js. */
const S = {
  analyse: null, demo: false, vue: "accueil",
  filtreA: "ouvertes", rechercheA: "", filtreQ: "ouvertes", modifsQ: {}, filtreR: "ouverts", voirDecides: false,
};
const TITRES = { accueil: "Accueil", actions: "Actions", questions: "Questions ouvertes", risques: "Risques", plan: "Plan de réalisation" };
const ORDRE_NIVEAUX = ["Critique", "Élevé", "Modéré", "Faible"];
const COULEUR_NIVEAU = { Critique: "rouge", "Élevé": "orange", "Modéré": "bleu", Faible: "vert" };

/* ---------- outils ---------- */
const $ = (id) => document.getElementById(id);

function el(tag, attrs, ...enfants) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e[k] = v;
    else if (v !== false && v !== null && v !== undefined) e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of enfants.flat(2)) if (c !== null && c !== undefined && c !== false) e.append(c instanceof Node ? c : String(c));
  return e;
}
const remplir = (noeud, ...enfants) => { noeud.replaceChildren(); enfants.flat(2).forEach((c) => c && noeud.append(c)); };
const montrer = (id, oui) => $(id).classList.toggle("cache", !oui);
const pourcent = (v) => (v === null || v === undefined ? "—" : Math.round(v * 100) + " %");
const pluriel = (n, mot) => n + " " + mot + (n > 1 ? "s" : "");
const icone = (chemin) => { const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.innerHTML = chemin; return s; };

function toast(texte, duree = 3500) {
  const t = $("toast");
  t.textContent = texte; montrer("toast", true);
  clearTimeout(toast.minuteur); toast.minuteur = setTimeout(() => montrer("toast", false), duree);
}

function erreur(texte) {
  const b = $("bandeau");
  b.className = "bandeau"; b.textContent = texte;
  b.onclick = () => montrer("bandeau", false);
  window.scrollTo({ top: 0, behavior: "smooth" });
}
const effacerErreur = () => montrer("bandeau", false);

async function occupe(texte, fn) {
  $("occupe-texte").textContent = texte; montrer("occupe", true);
  try { return await fn(); } finally { montrer("occupe", false); }
}

function ouvrir(url) {
  const f = window.open(url, "_blank", "noopener");
  if (!f) location.href = url;
}

/* ---------- moteur (worker Python) ---------- */
const moteur = (() => {
  const w = new Worker("moteur.js");
  const attente = new Map();
  let n = 0;
  w.onmessage = (e) => { attente.get(e.data.id)?.(e.data.resultat); attente.delete(e.data.id); };
  return { envoyer: (msg) => new Promise((ok) => { const id = ++n; attente.set(id, ok); w.postMessage({ id, ...msg }); }) };
})();

async function appel(nom, ...args) {
  effacerErreur();
  let jeton = "";
  if (!S.demo) {
    try { jeton = await AUTH.jeton(); } catch (e) {
      if (e.reconnexion) { versConnexion("Votre connexion Microsoft a expiré : reconnectez-vous."); return null; }
      erreur("Impossible de joindre Microsoft : vérifiez la connexion Internet."); return null;
    }
  }
  const r = await moteur.envoyer({ type: "appel", nom, args, jeton });
  (r.a_ouvrir || []).forEach(ouvrir);
  if (r.avertissement) toast(r.avertissement, 6000);
  if (!r.ok) {
    if (r.detail) console.warn(r.detail);
    if (r.reconnexion && !S.demo) { AUTH.seDeconnecter(); versConnexion(r.erreur); return null; }
    erreur(r.erreur || "Erreur inattendue.");
    return null;
  }
  return r.donnees;
}

/* ---------- démarrage et connexion ---------- */
function ecran(nom) {
  for (const e of ["attente", "connexion", "appli"]) montrer("ecran-" + e, e === nom);
}

function versConnexion(message) {
  ecran("connexion");
  $("connexion-erreur").textContent = message || "";
  montrer("connexion-erreur", !!message);
  $("btn-connexion").textContent = AUTH.connecte() ? "Réessayer" : "Se connecter avec Microsoft";
}

async function demarrer() {
  // Hors essais sur l'ordinateur : garde l'application sur le téléphone (ouverture rapide).
  if ("serviceWorker" in navigator && !["localhost", "127.0.0.1"].includes(location.hostname)) navigator.serviceWorker.register("sw.js").catch(() => {});
  try { navigator.storage?.persist?.(); } catch { /* facultatif */ }
  S.demo = new URLSearchParams(location.search).has("demo");
  try { await AUTH.traiterRetour(); } catch (e) { return versConnexion(e.message); }
  if (S.demo) return lancer();
  if (!CONFIG.client_id) return versConnexion("Cette copie de PilotPro mobile n'a pas d'identifiant d'application Microsoft : republiez-la depuis l'ordinateur.");
  if (!AUTH.connecte()) return versConnexion();
  return lancer();
}

async function lancer() {
  ecran("attente");
  $("attente-texte").textContent = "Démarrage du moteur… (la première fois, comptez une minute : il est ensuite gardé sur le téléphone)";
  let r;
  if (S.demo) r = await moteur.envoyer({ type: "demo" });
  else {
    let jeton;
    try { jeton = await AUTH.jeton(); } catch (e) {
      return versConnexion(e.reconnexion ? "Votre connexion Microsoft a expiré : reconnectez-vous." : "Impossible de joindre Microsoft : vérifiez la connexion Internet.");
    }
    r = await moteur.envoyer({ type: "demarrer", jeton });
  }
  if (!r.ok) {
    if (r.reconnexion) AUTH.seDeconnecter();
    return versConnexion(r.erreur);
  }
  $("attente-texte").textContent = "Lecture des classeurs…";
  const d = await appel("analyser");
  if (!d) { const msg = $("bandeau").textContent; return versConnexion(msg || "La lecture des classeurs a échoué."); }
  S.analyse = d;
  ecran("appli");
  afficher();
}

async function analyser() {
  const d = await occupe("Lecture des classeurs…", () => appel("analyser"));
  if (d) { S.analyse = d; afficher(); }
}

/* ---------- navigation ---------- */
function allerA(vue) {
  S.vue = vue;
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("actif", b.dataset.vue === vue));
  document.querySelectorAll(".vue").forEach((v) => v.classList.toggle("cache", v.id !== "v-" + vue));
  $("titre").textContent = TITRES[vue];
  montrer("btn-nouvelle", vue === "actions");
  majBarreQuestions();
  window.scrollTo(0, 0);
}

function afficher() {
  const d = S.analyse;
  $("sous-titre").textContent = "Analyse du " + d.date + (S.demo ? " · démonstration" : "");
  remplirDatalists();
  vueAccueil(); vueActions(); vueQuestions(); vueRisques(); vuePlan();
  allerA(S.vue);
}

function remplirDatalists() {
  const d = S.analyse;
  remplir($("dl-personnes"), d.personnes.map((p) => el("option", { value: p })));
  remplir($("dl-taches"), d.taches_plan.map((t) => el("option", { value: t.num }, t.libelle)));
}

/* ---------- accueil ---------- */
function tuile(valeur, texte, couleur, filtre) {
  return el("div", { class: "tuile " + couleur, onclick: filtre ? () => { S.filtreA = filtre; vueActions(); allerA("actions"); } : null },
    el("b", {}, valeur), el("span", {}, texte));
}

function vueAccueil() {
  const d = S.analyse, s = d.stats;
  const blocs = [el("div", { class: "tuiles" },
    tuile(s.ouvertes, "actions ouvertes", "sombre", "ouvertes"),
    tuile(s.en_retard, "en retard", "rouge", "retard"),
    tuile(s.proches, "à échéance proche", "orange", "proches"),
    tuile(pourcent(s.taux_realisation), "taux de réalisation", "vert", "realisees"))];

  // Changements d'échéance : violation ou autorisé ?
  const ch = d.changements_echeance || [];
  const attente = ch.filter((c) => !c.decision), decides = ch.filter((c) => c.decision);
  const carteEch = el("div", { class: "carte" }, el("h3", {}, "Échéances modifiées",
    el("span", { class: "compteur badge " + (attente.length ? "orange" : "") }, attente.length ? attente.length + " à décider" : "à jour")));
  const liste = el("div", { class: "liste" });
  if (!attente.length) liste.append(el("div", { class: "vide" }, ch.length ? "Rien à décider." : "Aucun changement d'échéance détecté depuis la dernière analyse."));
  for (const c of attente) {
    const note = el("input", { type: "text", placeholder: "Motif (facultatif)" });
    liste.append(el("div", { class: "item" }, ligneEcheance(c), note,
      el("div", { class: "boutons" },
        el("button", { class: "vert", onclick: () => decider(c, "autorise", note.value) }, "Autorisé"),
        el("button", { class: "rouge", onclick: () => decider(c, "violation", note.value) }, "Violation"))));
  }
  carteEch.append(liste);
  if (decides.length) {
    carteEch.append(el("button", { class: "lien", onclick: () => { S.voirDecides = !S.voirDecides; vueAccueil(); } },
      (S.voirDecides ? "Masquer" : "Voir") + " les décisions passées (" + decides.length + ")"));
    if (S.voirDecides) carteEch.append(el("div", { class: "liste" }, decides.map((c) => el("div", { class: "item" }, ligneEcheance(c),
      el("div", { class: "ligne" },
        el("span", { class: "badge " + (c.decision === "violation" ? "rouge" : "vert") }, c.decision === "violation" ? "Violation" : "Autorisé"),
        el("span", { class: "pousse doux petit" }, [c.origine === "application" ? "modifiée dans PilotPro" : "", c.note].filter(Boolean).join(" · ")),
        el("button", { onclick: () => decider(c, "", "") }, "Revoir"))))));
  }
  blocs.push(carteEch);

  // Rappels WhatsApp
  const resp = d.mails.filter((m) => !m.recap);
  blocs.push(el("div", { class: "carte" }, el("h3", {}, "Rappels WhatsApp"),
    el("div", { class: "liste" }, resp.length ? resp.map((m) => el("div", { class: "item ligne" },
      el("div", { class: "pousse" }, el("div", { class: "libelle" }, m.nom),
        el("div", { class: "meta" }, m.nb_retard ? el("span", { class: "alerte" }, m.nb_retard + " en retard") : null,
          m.nb_proches ? el("span", { class: "attention" }, m.nb_proches + " proche(s)") : null,
          m.nb_questions ? el("span", {}, pluriel(m.nb_questions, "question")) : null,
          m.escalade ? el("span", { class: "alerte" }, "relance " + (m.escalade === "ferme" ? "ferme" : "avec copie")) : null)),
      m.whatsapp ? el("button", { onclick: () => appel("ouvrir_whatsapp", m.cle) }, "WhatsApp")
        : el("span", { class: "doux petit" }, "pas de numéro")))
      : el("div", { class: "vide" }, "Personne à relancer cette semaine.")),
    el("p", { class: "doux petit", style: "margin:8px 0 0" }, "Le message est pré-rédigé : vous le relisez puis l'envoyez dans WhatsApp. Les mails, eux, partent depuis l'ordinateur.")));

  // Par responsable
  const parResp = Object.entries(s.par_responsable || {}).sort((a, b) => b[1].en_retard - a[1].en_retard || b[1].ouvertes - a[1].ouvertes);
  blocs.push(el("div", { class: "carte" }, el("h3", {}, "Par responsable"),
    el("div", { class: "liste" }, parResp.length ? parResp.map(([nom, v]) => el("div", {
      class: "item ligne cliquable", onclick: () => { S.rechercheA = nom; S.filtreA = "ouvertes"; vueActions(); allerA("actions"); },
    }, el("span", { class: "pousse libelle" }, nom), el("span", { class: "badge" }, v.ouvertes + " ouverte(s)"),
      v.en_retard ? el("span", { class: "badge rouge" }, v.en_retard + " en retard") : null))
      : el("div", { class: "vide" }, "Aucune action ouverte."))));

  if (d.anomalies.length) blocs.push(el("div", { class: "carte doux petit" },
    pluriel(d.anomalies.length, "point") + " à corriger dans les classeurs (le détail est sur l'ordinateur, Tableau de bord → Anomalies)."));
  remplir($("v-accueil"), blocs);
}

function ligneEcheance(c) {
  const ecart = c.ecart === null ? (c.apres ? "date ajoutée" : "date retirée") : (c.ecart > 0 ? "+" : "") + c.ecart + " j";
  return [el("div", { class: "ligne" }, el("span", { class: "num pousse" }, c.num),
    el("span", { class: "badge " + (c.ecart > 0 ? "orange" : "bleu") }, ecart)),
  el("div", { class: "libelle" }, c.libelle),
  el("div", { class: "meta" }, el("span", {}, c.responsables || "—"), el("span", {}, (c.avant || "—") + " → " + (c.apres || "—")),
    el("span", {}, "vu le " + c.detecte_le))];
}

async function decider(c, decision, note) {
  const r = await occupe("Enregistrement…", () => appel("decider_echeance", c.id, decision, note || ""));
  if (r) { S.analyse.changements_echeance = r; vueAccueil(); if (decision) toast(decision === "violation" ? "Classé en violation" : "Classé autorisé"); }
}

/* ---------- actions ---------- */
const FILTRES_A = {
  ouvertes: ["Ouvertes", (a) => a.ouverte], retard: ["En retard", (a) => a.en_retard], proches: ["Proches", (a) => a.proche],
  nouvelles: ["Nouvelles", (a) => a.nouvelle], realisees: ["Réalisées", (a) => a.statut === "Réalisée"], toutes: ["Toutes", () => true],
};

function puces(filtres, actif, choisir) {
  return el("div", { class: "puces" }, Object.entries(filtres).map(([cle, [libelle]]) =>
    el("button", { class: cle === actif ? "actif" : "", onclick: () => choisir(cle) }, libelle)));
}

function couleurStatut(a) {
  if (a.statut === "Réalisée") return "vert";
  if (a.statut === "Annulée") return "";
  if (a.en_retard || a.statut === "Bloquée") return "rouge";
  if (a.proche) return "orange";
  return a.statut === "En cours" ? "bleu" : "";
}

function vueActions() {
  const d = S.analyse;
  const recherche = el("input", { type: "search", class: "recherche", placeholder: "Rechercher (n°, mot, personne)", value: S.rechercheA });
  const zone = el("div");
  const dessiner = () => {
    const mots = S.rechercheA.toLowerCase().trim();
    const liste = d.actions.filter(FILTRES_A[S.filtreA][1])
      .filter((a) => !mots || (a.num + " " + a.libelle + " " + a.responsables).toLowerCase().includes(mots))
      .sort((a, b) => (b.en_retard - a.en_retard) || (b.proche - a.proche) || (a.echeance_iso || "9").localeCompare(b.echeance_iso || "9"));
    remplir(zone, el("p", { class: "doux petit", style: "margin:0 0 8px" }, pluriel(liste.length, "action")),
      el("div", { class: "carte liste" }, liste.length ? liste.map((a) => el("div", { class: "item cliquable", onclick: () => ficheAction(a) },
        el("div", { class: "ligne" }, el("span", { class: "num pousse" }, a.num), el("span", { class: "badge " + couleurStatut(a) }, a.statut)),
        el("div", { class: "libelle" }, a.libelle),
        el("div", { class: "meta" }, el("span", {}, a.responsables || "À attribuer"),
          a.echeance ? el("span", { class: a.en_retard ? "alerte" : a.proche ? "attention" : "" },
            a.en_retard ? "en retard de " + pluriel(a.jours_retard, "jour") + " (" + a.echeance + ")" : "pour le " + a.echeance) : el("span", {}, "sans échéance"),
          a.priorite === "Haute" ? el("span", {}, "priorité haute") : null)))
        : el("div", { class: "vide" }, "Aucune action ne correspond.")));
  };
  recherche.oninput = () => { S.rechercheA = recherche.value; dessiner(); };
  remplir($("v-actions"), recherche, puces(FILTRES_A, S.filtreA, (f) => { S.filtreA = f; vueActions(); }), zone);
  dessiner();
}

function champ(libelle, controle) { return el("label", { class: "champ" }, el("span", {}, libelle), controle); }
function selection(valeurs, choisie) {
  return el("select", {}, valeurs.concat(valeurs.includes(choisie) || !choisie ? [] : [choisie]).map((v) => el("option", { value: v, selected: v === choisie }, v)));
}

function feuille(...contenu) {
  remplir($("feuille-contenu"), contenu);
  const f = $("feuille");
  if (!f.open) f.showModal();
}
const fermerFeuille = () => $("feuille").close();

function ficheAction(a) {
  const d = S.analyse;
  const statut = selection(d.statuts_action, a.statut), prio = selection(d.priorites, a.priorite);
  const ech = el("input", { type: "date", value: a.echeance_iso });
  const resp = el("input", { type: "text", value: a.responsables, list: "dl-personnes", placeholder: "À attribuer" });
  const enregistrer = async () => {
    const modifs = Object.fromEntries([["statut", statut.value, a.statut], ["echeance", ech.value, a.echeance_iso],
      ["responsable", resp.value.trim(), a.responsables], ["priorite", prio.value, a.priorite]].filter(([, v, avant]) => v !== avant));
    if (!Object.keys(modifs).length) return fermerFeuille();
    fermerFeuille();
    const r = await occupe("Enregistrement dans le classeur…", () => appel("modifier_action", a.num, modifs));
    if (r) { toast("Action " + a.num + " enregistrée"); await analyser(); }
  };
  feuille(el("div", { class: "num" }, a.num + (a.taches ? " · " + a.taches : "")), el("h3", {}, a.libelle),
    a.livrable ? el("p", { class: "doux petit" }, "Livrable : " + a.livrable) : null,
    el("div", { style: "height:10px" }),
    champ("Statut", statut), el("div", { class: "deux" }, champ("Échéance", ech), champ("Priorité", prio)), champ("Responsable", resp),
    el("div", { class: "boutons" }, el("button", { onclick: fermerFeuille }, "Annuler"), el("button", { class: "principal", onclick: enregistrer }, "Enregistrer")),
    d.lien_classeur ? el("button", { class: "lien", style: "width:100%;margin-top:6px", onclick: () => appel("ouvrir_action", a.num) }, "Ouvrir la ligne dans Excel") : null);
}

function nouvelleAction() {
  const d = S.analyse;
  const lib = el("input", { type: "text", placeholder: "Ce qu'il faut faire" });
  const resp = el("input", { type: "text", list: "dl-personnes", placeholder: "À attribuer" });
  const ech = el("input", { type: "date" }), prio = selection(d.priorites, "Normale");
  const tache = el("input", { type: "text", list: "dl-taches", placeholder: "N° de tâche (facultatif)" });
  const creer = async () => {
    if (!lib.value.trim()) { lib.focus(); return toast("Décrivez l'action à réaliser."); }
    fermerFeuille();
    const r = await occupe("Création dans le classeur…", () => appel("creer_action",
      { libelle: lib.value.trim(), responsable: resp.value.trim(), echeance: ech.value, priorite: prio.value, tache: tache.value.trim() }));
    if (r) { toast("Action " + r.num + " créée"); await analyser(); }
  };
  feuille(el("h3", {}, "Nouvelle action"), el("div", { style: "height:10px" }), champ("Action", lib), champ("Responsable", resp),
    el("div", { class: "deux" }, champ("Échéance", ech), champ("Priorité", prio)), champ("Tâche du plan", tache),
    el("div", { class: "boutons" }, el("button", { onclick: fermerFeuille }, "Annuler"), el("button", { class: "principal", onclick: creer }, "Créer")));
}

/* ---------- questions : un seul enregistrement ---------- */
const FILTRES_Q = {
  ouvertes: ["Ouvertes", (q) => q.statut === "Ouverte" || q.statut === "En instruction"],
  sans: ["Sans responsable", (q) => !q.responsables], toutes: ["Toutes", () => true],
};

function vueQuestions() {
  const d = S.analyse;
  const liste = d.questions.filter((q) => S.modifsQ[q.num] || FILTRES_Q[S.filtreQ][1](q));
  remplir($("v-questions"), puces(FILTRES_Q, S.filtreQ, (f) => { S.filtreQ = f; vueQuestions(); }),
    el("p", { class: "doux petit", style: "margin:0 0 8px" }, liste.length + " question(s) sur " + d.questions.length),
    el("div", { class: "carte liste" }, liste.length ? liste.map(carteQuestion) : el("div", { class: "vide" }, "Aucune question ne correspond.")));
  majBarreQuestions();
}

function carteQuestion(q) {
  const m = S.modifsQ[q.num] || {};
  const val = (cle, avant) => (cle in m ? m[cle] : avant);
  const resp = el("input", { type: "text", value: val("responsable", q.responsables), list: "dl-personnes", placeholder: "Responsable à attribuer" });
  const ech = el("input", { type: "date", value: val("echeance", q.echeance_iso) });
  const statut = selection(S.analyse.statuts_question, val("statut", q.statut));
  const carte = el("div", { class: "item question" + (q.num in S.modifsQ ? " modifiee" : "") },
    el("div", { class: "ligne" }, el("span", { class: "num pousse" }, q.num), q.responsables ? null : el("span", { class: "badge orange" }, "sans responsable")),
    el("div", { class: "libelle" }, q.intitule), resp, el("div", { class: "deux" }, ech, statut));
  const change = () => {
    const modifs = Object.fromEntries([["responsable", resp.value.trim(), q.responsables], ["echeance", ech.value, q.echeance_iso],
      ["statut", statut.value, q.statut]].filter(([, v, avant]) => v !== avant));
    if (Object.keys(modifs).length) S.modifsQ[q.num] = modifs; else delete S.modifsQ[q.num];
    carte.classList.toggle("modifiee", q.num in S.modifsQ);
    majBarreQuestions();
  };
  resp.oninput = ech.oninput = statut.onchange = change;
  return carte;
}

function majBarreQuestions() {
  const n = Object.keys(S.modifsQ).length;
  montrer("barre-questions", S.vue === "questions" && n > 0);
  $("btn-q-enregistrer").textContent = "Enregistrer " + pluriel(n, "question");
}

async function enregistrerQuestions() {
  const r = await occupe("Enregistrement dans le classeur…", () => appel("modifier_questions", S.modifsQ));
  if (!r) return;
  r.enregistrees.forEach((num) => delete S.modifsQ[num]);  // celles en échec restent à l'écran, à réessayer
  const echecs = Object.entries(r.echecs);
  if (r.enregistrees.length) { toast(pluriel(r.enregistrees.length, "question") + " enregistrée(s)"); await analyser(); }
  else vueQuestions();
  if (echecs.length) erreur(echecs.length + " question(s) non enregistrée(s) — " + echecs.map(([n, e]) => n + " : " + e).join(" ; "));
}

/* ---------- risques ---------- */
function vueRisques() {
  const tous = S.analyse.risques;
  const niveaux = ORDRE_NIVEAUX.filter((n) => tous.some((x) => x.niveau === n));
  const filtres = { ouverts: ["Ouverts", (x) => x.statut !== "Clos"] };
  for (const n of niveaux) filtres[n] = [n, (x) => x.niveau === n && x.statut !== "Clos"];
  filtres.tous = ["Tous", () => true];
  if (!filtres[S.filtreR]) S.filtreR = "ouverts";
  const rang = (x) => { const i = ORDRE_NIVEAUX.indexOf(x.niveau); return i < 0 ? 9 : i; };
  const liste = tous.filter(filtres[S.filtreR][1]).sort((a, b) => rang(a) - rang(b));
  remplir($("v-risques"), puces(filtres, S.filtreR, (f) => { S.filtreR = f; vueRisques(); }),
    el("p", { class: "doux petit", style: "margin:0 0 8px" }, pluriel(liste.length, "risque")),
    el("div", { class: "carte liste" }, liste.length ? liste.map((x) => el("div", { class: "item" },
      el("div", { class: "ligne" }, el("span", { class: "num pousse" }, x.num + (x.categorie ? " · " + x.categorie : "")),
        el("span", { class: "badge " + (COULEUR_NIVEAU[x.niveau] || "") }, x.niveau || "non noté")),
      el("div", { class: "libelle" }, x.intitule),
      el("div", { class: "meta" }, el("span", {}, x.proprietaires || "sans propriétaire"), x.echeance ? el("span", {}, "pour le " + x.echeance) : null,
        el("span", {}, x.statut), x.avancement ? el("span", {}, x.avancement) : null,
        x.p && x.i ? el("span", {}, "P" + x.p + " × I" + x.i) : null)))
      : el("div", { class: "vide" }, "Aucun risque ne correspond.")));
}

/* ---------- plan ---------- */
function vuePlan() {
  const d = S.analyse, auj = d.aujourdhui;
  const phases = {};
  d.plan.forEach((t) => (phases[t.onglet] = phases[t.onglet] || []).push(t));
  const moyenne = (ts) => Math.round(ts.reduce((s, t) => s + (t.avancement || 0), 0) / ts.length);
  remplir($("v-plan"), el("p", { class: "doux petit", style: "margin:0 0 8px" }, d.plan.length + " tâches · avancement moyen " + (d.plan.length ? moyenne(d.plan) : 0) + " %"),
    el("div", { class: "carte" }, Object.entries(phases).map(([onglet, ts]) => {
      const m = moyenne(ts);
      return el("details", { class: "phase" },
        el("summary", {}, el("div", { class: "ligne" }, el("span", { class: "pousse libelle" }, onglet), el("span", { class: "doux petit" }, ts.length + " tâches · " + m + " %")),
          el("div", { class: "barre-av" + (m === 100 ? " vert" : "") }, el("i", { style: "width:" + m + "%" }))),
        el("div", { class: "liste", style: "padding-bottom:10px" }, ts.map((t) => {
          const fin = t.echeance || t.fin_phase;
          const retard = fin && fin < auj && t.statut !== "Réalisée" && t.statut !== "Annulée";
          return el("div", { class: "item" },
            el("div", { class: "ligne" }, el("span", { class: "num pousse" }, t.num), el("span", { class: "badge " + (t.statut === "Réalisée" ? "vert" : retard ? "rouge" : "") }, t.statut || "—")),
            el("div", {}, t.libelle),
            el("div", { class: "meta" }, el("span", {}, t.responsable || "—"),
              fin ? el("span", { class: retard ? "alerte" : "" }, (t.echeance ? "échéance " : "fin de phase ") + fin.split("-").reverse().join("/")) : null,
              el("span", {}, t.avancement + " %")),
            el("div", { class: "barre-av" + (t.avancement >= 100 ? " vert" : "") }, el("i", { style: "width:" + Math.min(100, t.avancement) + "%" })));
        })));
    })));
}

/* ---------- menu ---------- */
function menu() {
  feuille(el("h3", {}, "PilotPro mobile"),
    el("p", { class: "doux petit" }, S.demo ? "Mode démonstration : classeurs fictifs, rien n'est écrit en ligne." : "Connecté à votre compte Microsoft."),
    el("p", { class: "doux petit" }, "Sur le téléphone : consulter, mettre à jour les actions et les questions, décider des échéances, relancer par WhatsApp. "
      + "Envoi des mails, modèles, équipe et réglages : sur l'ordinateur."),
    el("div", { class: "boutons", style: "flex-direction:column" },
      el("button", { onclick: () => { fermerFeuille(); analyser(); } }, "Relire les classeurs"),
      S.demo ? el("button", { onclick: () => { location.href = location.pathname; } }, "Quitter la démonstration")
        : el("button", { class: "rouge", onclick: () => { AUTH.seDeconnecter(); location.href = location.pathname; } }, "Se déconnecter")),
    el("p", { class: "doux petit centre", style: "margin-top:12px" }, "Version " + CONFIG.version));
}

/* ---------- branchements ---------- */
document.body.append(el("datalist", { id: "dl-personnes" }), el("datalist", { id: "dl-taches" }));
document.querySelectorAll("nav button").forEach((b) => (b.onclick = () => allerA(b.dataset.vue)));
$("btn-actualiser").onclick = analyser;
$("btn-menu").onclick = menu;
$("btn-nouvelle").onclick = nouvelleAction;
$("btn-q-enregistrer").onclick = enregistrerQuestions;
$("btn-q-annuler").onclick = () => { S.modifsQ = {}; vueQuestions(); };
$("btn-connexion").onclick = () => (AUTH.connecte() ? lancer() : AUTH.seConnecter());
$("btn-demo").onclick = () => { location.href = location.pathname + "?demo"; };
$("feuille").onclick = (e) => { if (e.target.id === "feuille") fermerFeuille(); };  // toucher le fond ferme la fenêtre
demarrer();
