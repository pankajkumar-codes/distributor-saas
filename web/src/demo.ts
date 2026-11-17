/** True only in the local demo's web build (demo/Dockerfile sets VITE_DEMO); a production build never has it. */
export const isDemo = () => import.meta.env.VITE_DEMO === "1";
