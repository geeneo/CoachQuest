// The CoachQuest logo (raster art on navy, from the logo pack; see public/brand).
const SRC = {
  mark: ["/brand/logo.webp", 440, 185],
  word: ["/brand/logo-word.webp", 480, 57],
  full: ["/brand/logo-full.webp", 760, 360],
};

export default function Logo({ variant = "mark", className = "" }) {
  const [src, width, height] = SRC[variant];
  return <img src={src} width={width} height={height} alt="CoachQuest" className={`logo logo-${variant} ${className}`} />;
}
