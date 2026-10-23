import React from "react";

const EXAMPLES = [
  {
    brand: "NASA",
    note: "Artemis exploration campaign · illustrative concept",
    kit: "/workflow/examples/nasa-kit.jpg",
    layout: "/workflow/examples/nasa-layout.png",
    background: "/workflow/examples/nasa-background.jpg",
    final: "/workflow/examples/nasa-final.jpg",
  },
  {
    brand: "Xero",
    note: "Small-business campaign · illustrative concept",
    kit: "/workflow/examples/xero-kit.jpg",
    layout: "/workflow/examples/xero-layout.png",
    background: "/workflow/examples/xero-background.jpg",
    final: "/workflow/examples/xero-final.jpg",
  },
];

const STAGES = [
  {
    key: "kit",
    title: "01 · Brand input",
    detail: "Brief + selected brand imagery, marks, palette, and rules.",
  },
  {
    key: "layout",
    title: "02 · Plan",
    detail: "Exact copy and assets placed on a transparent canvas.",
    checkerboard: true,
  },
  {
    key: "background",
    title: "03 · Generate",
    detail: "A text-free Seedream scene; exact foreground is added after generation.",
  },
  {
    key: "final",
    title: "04 · Composite",
    detail: "Code overlays the exact foreground; text stays crisp.",
  },
];

const PIPELINE = [
  ["Brief + brand kit", "assets · rules · palette"],
  ["Plan", "copy · placements · contrast"],
  ["Generate", "Seedream 5.0 Lite · background"],
  ["Composite", "exact text · real assets · layers"],
  ["Edit + export", "move · resize · rewrite · replace"],
];

export default function WorkflowPage() {
  return (
    <main className="workflow-page">
      <header className="workflow-intro">
        <div className="workflow-kicker">CRUX · LAYOUT-FIRST IMAGE PIPELINE</div>
        <h1>Brand kit in. Editable creative out.</h1>
        <p>
          A technical overview of how Crux plans an ad before image generation,
          keeps brand elements deterministic, and returns a layered canvas rather
          than a flattened image.
        </p>
      </header>

      <section className="workflow-pipeline" aria-label="Crux end-to-end pipeline">
        {PIPELINE.map(([title, detail], index) => (
          <React.Fragment key={title}>
            <div className="workflow-node">
              <b>{title}</b>
              <span>{detail}</span>
            </div>
            {index < PIPELINE.length - 1 && (
              <span className="workflow-arrow" aria-hidden="true">→</span>
            )}
          </React.Fragment>
        ))}
      </section>

      <section className="workflow-technical">
        <div className="workflow-section-heading">
          <div>
            <div className="workflow-kicker">WHAT EACH STAGE PRODUCES</div>
            <h2>Same pipeline, different brand systems.</h2>
          </div>
          <p>Transparent previews are shown on a checkerboard.</p>
        </div>

        {EXAMPLES.map((example) => (
          <article className="workflow-example" key={example.brand}>
            <div className="workflow-example-heading">
              <div>
                <h3>{example.brand}</h3>
                <p>{example.note}</p>
              </div>
              <span className="workflow-model-badge">Seedream 5.0 Lite · T2I sample</span>
            </div>
            <div className="workflow-stage-grid">
              {STAGES.map((stage) => (
                <figure className="workflow-stage" key={stage.key}>
                  <div className={`workflow-stage-image${stage.checkerboard ? " checkerboard" : ""}`}>
                    <img src={example[stage.key]} alt={`${example.brand} — ${stage.title}`} loading="lazy" />
                  </div>
                  <figcaption>
                    <b>{stage.title}</b>
                    <span>{stage.detail}</span>
                  </figcaption>
                </figure>
              ))}
            </div>
            <div className="workflow-layer-strip">
              <div>
                <b>05 · Editable output</b>
                <span>
                  Manifest-backed layers: background raster · image assets · shapes · live text.
                  Edit copy or geometry independently; repaint the background without flattening
                  the foreground.
                </span>
              </div>
              <div className="workflow-layer-tags" aria-label="Editable layer types">
                {["Background", "Brand asset", "Shape", "Text"].map((layer) => (
                  <span key={layer}>{layer}</span>
                ))}
              </div>
            </div>
          </article>
        ))}
      </section>

      <section className="workflow-details">
        <article>
          <div className="workflow-kicker">DATA FLOW</div>
          <h2>Models propose. Code owns fidelity.</h2>
          <ol>
            <li><b>Ingest:</b> index the brand kit into assets, metadata, palette, and rules.</li>
            <li><b>Plan:</b> produce a brief, exact copy, placements, and a contrast-aware layout.</li>
            <li><b>Render proof:</b> draw the selected foreground to a transparent PNG.</li>
            <li><b>Generate background:</b> send the proof and art direction to Seedream 5.0 Lite Edit.</li>
            <li><b>Composite + package:</b> draw exact copy/assets over the background and save a layered manifest.</li>
          </ol>
        </article>
        <article>
          <div className="workflow-kicker">WHAT YOU CAN DO NEXT</div>
          <h2>Iterate at the layer you mean.</h2>
          <ul>
            <li>Generate multiple layout concepts and aspect ratios from one brief.</li>
            <li>Rewrite or restyle text without asking an image model to redraw it.</li>
            <li>Move, resize, or replace brand assets and shapes on the canvas.</li>
            <li>Request a background change while preserving the live foreground layers.</li>
            <li>Inspect prompts, reference images, generated backgrounds, and final composites.</li>
          </ul>
        </article>
      </section>
      <p className="workflow-disclaimer">
        NASA and Xero are shown as illustrative, independently created examples—not official
        campaigns or endorsements. These clean sample backgrounds use Seedream 5.0 Lite text-to-image.
        Seedream 5.0 Lite Edit is the configured default for new jobs and receives the layout reference;
        it can echo pixels from that reference, so background separation is not guaranteed by the model.
      </p>
    </main>
  );
}
