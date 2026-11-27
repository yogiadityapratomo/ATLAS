// Salin file font IBM Plex (SIL OFL 1.1) dari node_modules/@fontsource ke frontend/vendor/fonts.
// Server tidak punya internet, jadi font di-vendor (di-commit) seperti jQuery. Jalankan: npm run fonts
import { copyFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const out = join("frontend", "vendor", "fonts");
mkdirSync(out, { recursive: true });

const files = [
  ["ibm-plex-sans", [400, 500, 600, 700]],
  ["ibm-plex-sans-condensed", [500, 600, 700]],
];
for (const [family, weights] of files) {
  const dir = join("node_modules", "@fontsource", family, "files");
  for (const w of weights) {
    const name = `${family}-latin-${w}-normal.woff2`;
    copyFileSync(join(dir, name), join(out, name));
    console.log("copied", name);
  }
}
copyFileSync(join("node_modules", "@fontsource", "ibm-plex-sans", "LICENSE"), join(out, "OFL-IBM-Plex.txt"));
console.log("copied OFL-IBM-Plex.txt");
