// Body outline, front and back, with the muscles an exercise works coloured in: main muscles
// strong, helping muscles light. Our own drawing, so no licence questions. Muscle names are the
// exercise library's (strength.py): quadriceps, hamstrings, glutes, calves, ...

// Each muscle: shapes on the front and/or back view (viewBox 0 0 100 200, body centred on x=50).
const ell = (cx, cy, rx, ry) => ({ cx, cy, rx, ry });
const pair = (cx, cy, rx, ry) => [ell(cx, cy, rx, ry), ell(100 - cx, cy, rx, ry)];
const path = (d) => ({ d });
const mirror = (d) => [path(d), path(d.replace(/(-?\d+(\.\d+)?),/g, (_, x) => `${100 - Number(x)},`))];

const FRONT = {
  neck: [path("M45,24 h10 v7 h-10 Z")],
  shoulders: pair(31, 39, 7.5, 6.5),
  chest: mirror("M37,36 Q47,33 49,37 L49,53 Q41,56 37,50 Z"),
  biceps: pair(25, 56, 4.5, 10),
  forearms: pair(21, 81, 4, 12),
  abdominals: [path("M42,57 h16 v33 q-8,5 -16,0 Z")],
  abductors: pair(35, 99, 4, 7),
  adductors: pair(46.5, 112, 3, 11),
  quadriceps: pair(40, 124, 6.5, 19),
};
const BACK = {
  neck: [path("M45,24 h10 v5 h-10 Z")],
  traps: [path("M41,28 L59,28 L65,38 L50,50 L35,38 Z")],
  shoulders: pair(31, 39, 7.5, 6.5),
  lats: mirror("M36,45 L46,53 L46,75 Q38,71 35,59 Z"),
  "middle back": [path("M47,51 h6 v18 h-6 Z")],
  "lower back": [path("M43,72 h14 v15 q-7,3 -14,0 Z")],
  triceps: pair(25, 56, 4.5, 10),
  forearms: pair(21, 81, 4, 12),
  glutes: pair(43, 99, 7.5, 8.5),
  hamstrings: pair(41, 126, 6, 17),
  calves: pair(40, 163, 5, 12),
};

// The body underneath, in the panel colour.
function Body() {
  return (
    <g className="mm-body">
      <circle cx="50" cy="14" r="10" />
      <path d="M33,32 Q50,26 67,32 L64,92 Q50,98 36,92 Z" />
      {[19, 81].map((x) => (
        <rect key={x} x={x - 6} y="36" width="12" height="62" rx="6" />
      ))}
      {[40, 60].map((x) => (
        <rect key={x} x={x - 8} y="92" width="16" height="96" rx="8" />
      ))}
    </g>
  );
}

function View({ shapes, label, primary, secondary }) {
  return (
    <svg viewBox="0 0 100 200" role="img" aria-label={label}>
      <Body />
      {Object.entries(shapes).map(([muscle, list]) => {
        const cls = primary.includes(muscle) ? "mm-primary" : secondary.includes(muscle) ? "mm-secondary" : "mm-rest";
        return list.map((s, i) =>
          s.d ? (
            <path key={muscle + i} d={s.d} className={cls}>
              <title>{muscle}</title>
            </path>
          ) : (
            <ellipse key={muscle + i} {...s} className={cls}>
              <title>{muscle}</title>
            </ellipse>
          ),
        );
      })}
      <text x="50" y="198" textAnchor="middle" className="mm-label">
        {label}
      </text>
    </svg>
  );
}

export default function MuscleMap({ primary = [], secondary = [] }) {
  return (
    <div className="muscle-map" title={`Main: ${primary.join(", ")}${secondary.length ? `; also: ${secondary.join(", ")}` : ""}`}>
      <View shapes={FRONT} label="Front" primary={primary} secondary={secondary} />
      <View shapes={BACK} label="Back" primary={primary} secondary={secondary} />
    </div>
  );
}
