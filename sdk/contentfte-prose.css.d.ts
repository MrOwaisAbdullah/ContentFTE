// Type declaration for the stylesheet side-effect import:
//   import "content-fte/contentfte-prose.css";
// Bundlers load the real .css (exports "default" condition); this module
// exists so TypeScript resolves the path without ambient *.css declarations.
export {};
