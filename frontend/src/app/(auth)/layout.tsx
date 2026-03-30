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
        style={{ background: "linear-gradient(160deg, #fff8f0 0%, #fff4e8 40%, #fff0e0 100%)" }}
      >
        {/* Warm amber glow — top left */}
        <div
          className="absolute -top-24 -left-24 h-96 w-96 rounded-full pointer-events-none"
          style={{ background: "radial-gradient(circle, rgba(251,191,36,0.18) 0%, transparent 70%)" }}
        />
        {/* Soft magenta glow — bottom right */}
        <div
          className="absolute -bottom-24 -right-16 h-96 w-96 rounded-full pointer-events-none"
          style={{ background: "radial-gradient(circle, rgba(217,70,239,0.10) 0%, transparent 70%)" }}
        />

        {/* Thin right-edge accent line */}
        <div className="absolute right-0 inset-y-0 w-px bg-gradient-to-b from-transparent via-amber-200/70 to-transparent" />

        {/* Content — centred */}
        <div className="relative z-10 flex flex-col items-center gap-7 px-16 text-center w-full max-w-sm mx-auto">
          {/* Logo card */}
          <div className="w-full rounded-2xl bg-white px-10 py-8 shadow-md border border-neutral-100 flex items-center justify-center">
            <Image
              src="/Logo_withTagline.svg"
              alt="Logikality"
              width={220}
              height={60}
              priority
              style={{ width: "auto", height: "auto", maxWidth: 220 }}
            />
          </div>

          {/* Amber-to-magenta rule */}
          <div className="h-0.5 w-20 rounded-full" style={{ background: "linear-gradient(90deg, #f59e0b, #d946ef)" }} />

          {/* Description */}
          <p className="text-sm text-neutral-400 leading-relaxed tracking-wide">
            Decision-ready AI for mortgage operations
          </p>

        </div>
      </div>

      {/* Right panel - form */}
      <div className="flex flex-1 items-center justify-center bg-white px-6">
        <div className="w-full max-w-md">
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
