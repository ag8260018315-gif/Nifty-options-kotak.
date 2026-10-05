// A short, honest description of EdgeDesk shown on the loading and "can't reach the server" screens, so a visitor (or a search engine)
// that arrives while the backend is waking up still sees what this site is instead of an empty page.
export default function AboutBlurb() {
  return (
    <section data-testid="about-blurb" className="mx-auto mt-8 max-w-[520px] px-6 text-center text-[13.5px] leading-relaxed text-[#8c98ae]">
      <h1 className="font-heading text-[15px] font-semibold text-[#c3cbda]">EdgeDesk: options analytics for NIFTY, BANKNIFTY and FINNIFTY</h1>
      <p className="mt-2">Live option chain, Greeks, PCR and open-interest analytics, charts and an AI analyst. Premium adds SENSEX, stock pages and alerts. 7-day free trial. For information only, not investment advice.</p>
    </section>
  );
}
