/* Moteur de PilotPro sur le téléphone : le code Python de l'ordinateur, exécuté par Pyodide
   dans un « worker » (à l'écart de l'affichage, qui reste fluide pendant les calculs). */
importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js");

let pont = null;

async function charger() {
  const py = await loadPyodide();
  const frais = { cache: "no-cache" };  // revalide auprès du serveur (le cache hors ligne, lui, répond tout de suite)
  const liste = await (await fetch("py/fichiers.json", frais)).json();
  const [, ...fichiers] = await Promise.all([
    py.loadPackage(["jinja2"]),
    ...liste.map(async (f) => [f, await (await fetch("py/" + f, frais)).text()]),
  ]);
  for (const [f, texte] of fichiers) {
    const dossier = "/app/" + f.split("/").slice(0, -1).join("/");
    py.FS.mkdirTree(dossier);
    py.FS.writeFile("/app/" + f, texte);
  }
  py.runPython("import sys; sys.path.insert(0, '/app')");
  pont = py.pyimport("pont");
}

let pret = null;

onmessage = async (e) => {
  const { id, type, nom, args, jeton } = e.data;
  try {
    if (!pret) pret = charger();
    await pret;
    let r;
    if (type === "demarrer") r = pont.demarrer(jeton);
    else if (type === "demo") r = pont.demarrer_demo();
    else r = pont.appeler(nom, JSON.stringify(args || []), jeton || "");
    postMessage({ id, resultat: JSON.parse(r) });
  } catch (err) {
    console.error(err);
    if (String(err).includes("loadPyodide") || !pont) pret = null;  // nouvel essai au prochain appel
    postMessage({ id, resultat: { ok: false, erreur: pont ? "Erreur inattendue : " + String(err.message || err).slice(-300)
      : "Le moteur de PilotPro n'a pas pu être chargé : vérifiez la connexion Internet puis réessayez." } });
  }
};
