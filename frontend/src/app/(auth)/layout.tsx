import Image from "next/image";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen">
      {/* Left panel - branding */}
      <div
        className="hidden lg:flex lg:w-1/2 items-center justify-center relative overflow-hidden"
        style={{ background: "linear-gradient(160deg, #fff8f0 0%, #fff4e8 45%, #ffeedd 100%)" }}
      >
        {/* Animated pulse glow behind the card */}
        <div
          className="absolute inset-0 flex items-center justify-center pointer-events-none"
        >
          <div
            style={{
              width: 420,
              height: 420,
              borderRadius: "50%",
              background: "radial-gradient(circle, rgba(251,191,36,0.22) 0%, rgba(249,115,22,0.10) 40%, transparent 70%)",
              animation: "pulseGlow 4s ease-in-out infinite",
            }}
          />
        </div>

        {/* Decorative ring 1 */}
        <div
          className="absolute pointer-events-none"
          style={{
            width: 560,
            height: 560,
            borderRadius: "50%",
            border: "1px solid rgba(251,191,36,0.15)",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -50%)",
          }}
        />
        {/* Decorative ring 2 */}
        <div
          className="absolute pointer-events-none"
          style={{
            width: 700,
            height: 700,
            borderRadius: "50%",
            border: "1px solid rgba(251,191,36,0.08)",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -50%)",
          }}
        />

        {/* Corner glows */}
        <div
          className="absolute -top-20 -left-20 h-80 w-80 rounded-full pointer-events-none"
          style={{ background: "radial-gradient(circle, rgba(251,191,36,0.15) 0%, transparent 70%)" }}
        />
        <div
          className="absolute -bottom-20 -right-12 h-72 w-72 rounded-full pointer-events-none"
          style={{ background: "radial-gradient(circle, rgba(217,70,239,0.08) 0%, transparent 70%)" }}
        />

        {/* Right-edge accent */}
        <div className="absolute right-0 inset-y-0 w-px bg-gradient-to-b from-transparent via-amber-300/50 to-transparent" />

        {/* Content */}
        <div className="relative z-10 flex flex-col items-center gap-8 px-16 text-center w-full max-w-sm mx-auto">

          {/* Logo card — orange gradient matching Sign In button */}
          <div
            className="w-full rounded-3xl flex flex-col items-center justify-center px-10 py-10"
            style={{
              background: "linear-gradient(135deg, oklch(0.750 0.170 65) 0%, oklch(0.680 0.190 55) 100%)",
              boxShadow: "0 8px 40px oklch(0.750 0.170 65 / 0.40), 0 2px 12px rgba(0,0,0,0.10)",
              border: "1px solid rgba(255,255,255,0.20)",
            }}
          >
            <Image
              src="/Logo_rev_no-tagline.svg"
              alt="Logikality"
              width={180}
              height={60}
              priority
              style={{ width: "auto", height: "auto", maxWidth: 180 }}
            />
          </div>

          {/* Tagline */}
          <div className="flex flex-col items-center gap-3">
            <p className="text-base font-medium text-neutral-700 leading-relaxed tracking-wide">
              Decision-ready AI for mortgage operations
            </p>
            {/* Gradient rule */}
            <div
              className="h-0.5 w-16 rounded-full"
              style={{ background: "linear-gradient(90deg, #f59e0b, #f97316, #d946ef)" }}
            />
            {/* Trust line */}
            <p className="text-xs text-neutral-400 tracking-wider uppercase">
              Trusted by title professionals
            </p>
          </div>

        </div>

        {/* Keyframe injection */}
        <style>{`
          @keyframes pulseGlow {
            0%, 100% { opacity: 0.7; transform: scale(1); }
            50% { opacity: 1; transform: scale(1.08); }
          }
        `}</style>
      </div>

      {/* Right panel - form */}
      <div className="flex flex-1 items-center justify-center bg-white px-6">
        <div className="w-full max-w-md">

          {/* Brand logo above form — desktop only */}
          <div className="mb-6 hidden lg:flex items-center justify-center">
            <Image
              src="/Logo_withTagline.svg"
              alt="Logikality"
              width={140}
              height={38}
              priority
              style={{ width: "auto", height: "auto", maxWidth: 140 }}
            />
          </div>

          {/* Mobile logo */}
          <div className="mb-8 flex items-center justify-center lg:hidden">
            <Image
              src="/Logo_withTagline.svg"
              alt="Logikality"
              width={200}
              height={56}
              priority
              style={{ width: "auto", height: "auto", maxWidth: 200 }}
            />
          </div>

          {children}
        </div>
      </div>
    </div>
  );
}
