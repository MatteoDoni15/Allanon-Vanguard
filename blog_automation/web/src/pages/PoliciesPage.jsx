import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { fetchPolicies, addPolicy, deletePolicy } from "../api.js";

// A few ready-made example policies the user can click to prefill the form.
// They mirror the style of NorthLedger's existing compliance documents.
const EXAMPLES = [
  {
    title: "Tassi di interesse e rendimenti",
    text:
      "Ogni contenuto che cita tassi di interesse o rendimenti deve specificare che i tassi sono variabili e soggetti a modifica senza preavviso. È vietato presentare un rendimento come garantito o privo di rischio. I rendimenti passati non sono indicativi di quelli futuri e questa avvertenza va sempre inclusa.",
  },
  {
    title: "Trasparenza su costi e commissioni",
    text:
      "Qualsiasi riferimento a costi, canoni o commissioni deve essere accurato e coerente con il tariffario ufficiale vigente. Non è consentito dichiarare un servizio come 'totalmente gratuito' se sono previste commissioni in specifiche condizioni: in tal caso vanno indicate chiaramente le eccezioni.",
  },
  {
    title: "Linguaggio e urgenza promozionale",
    text:
      "Il linguaggio promozionale che induce urgenza (es. 'offerta a tempo limitato', 'affrettati', 'non perdere questa occasione') richiede l'approvazione preventiva dell'ufficio legale. I confronti con concorrenti citati per nome devono essere fattuali, documentabili e mai denigratori.",
  },
  {
    title: "Protezione dati e privacy",
    text:
      "Non vendiamo i dati di transazione dei clienti a terze parti per scopi di marketing. Ogni contenuto che menziona l'uso dei dati deve riflettere questo principio e indicare che il cliente può opporsi al trattamento per finalità promozionali in qualsiasi momento dalle impostazioni dell'account.",
  },
];

export default function PoliciesPage() {
  const [policies, setPolicies] = useState([]);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    refresh();
  }, []);

  function refresh() {
    fetchPolicies()
      .then(setPolicies)
      .catch((e) => setError(e.message));
  }

  async function onSubmit(e) {
    e.preventDefault();
    if (!title.trim() || !text.trim() || saving) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await addPolicy({ title: title.trim(), text: text.trim() });
      setTitle("");
      setText("");
      setNotice(
        "Policy salvata. Verrà inserita nell'indice vettoriale e usata dal fact-check alla prossima generazione."
      );
      refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function onDelete(docId) {
    await deletePolicy(docId).catch((e) => setError(e.message));
    refresh();
  }

  function useExample(ex) {
    setTitle(ex.title);
    setText(ex.text);
  }

  return (
    <div className="layout policies-layout">
      {/* ── left: add a new policy ─────────────────────────────────── */}
      <section className="panel">
        <h2>Aggiungi una policy</h2>
        <p className="muted">
          Le policy vengono salvate e inserite nel DB vettoriale. Durante la
          generazione, il nodo <code>policy_fact_check</code> recupera quelle più
          pertinenti e verifica che il testo del blog le rispetti.
        </p>

        <form onSubmit={onSubmit} className="gen-form">
          <label className="field">
            <span>Titolo</span>
            <input
              type="text"
              placeholder="es. Tassi di interesse e rendimenti"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label className="field">
            <span>Testo della policy</span>
            <textarea
              rows={7}
              placeholder="Scrivi qui la regola di compliance…"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </label>
          <button type="submit" className="primary" disabled={saving || !title.trim() || !text.trim()}>
            {saving ? "Salvataggio…" : "＋ Salva policy"}
          </button>
        </form>

        {error && <div className="alert error">⚠ {error}</div>}
        {notice && <div className="alert success">✓ {notice}</div>}

        <h3 className="examples-title">Esempi pronti (clicca per compilare)</h3>
        <ul className="example-list">
          {EXAMPLES.map((ex) => (
            <li key={ex.title}>
              <button type="button" className="example-btn" onClick={() => useExample(ex)}>
                {ex.title}
              </button>
            </li>
          ))}
        </ul>
      </section>

      {/* ── right: existing policies ───────────────────────────────── */}
      <section className="panel policies-list-panel">
        <h2>Policy attive ({policies.length})</h2>
        <Link to="/" className="muted">← torna al generatore</Link>
        {policies.length === 0 && <p className="muted">Ancora nessuna policy.</p>}
        <ul className="policy-list">
          {policies.map((p) => (
            <li key={p.doc_id} className="policy-item">
              <div className="policy-head">
                <b>{p.title}</b>
                <button
                  className="link-btn"
                  onClick={() => onDelete(p.doc_id)}
                  title="Elimina policy"
                >
                  ✕
                </button>
              </div>
              <code className="policy-id">{p.doc_id}</code>
              <p className="policy-text">{p.text}</p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
