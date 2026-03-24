import Image from "next/image";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen">
      {/* Left panel - branding */}
      <div className="hidden lg:flex lg:w-1/2 bg-brand-charcoal items-center justify-center relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-brand-charcoal via-brand-charcoal to-brand-magenta/15" />
        {/* Decorative circles */}
        <div className="absolute top-20 left-20 h-64 w-64 rounded-full bg-brand-amber/5 blur-3xl" />
        <div className="absolute bottom-20 right-20 h-48 w-48 rounded-full bg-brand-magenta/5 blur-3xl" />
        <div className="relative z-10 flex flex-col items-center gap-6 px-12 text-center">
          <Image
            src="/logikality_logo.png"
            alt="Logikality"
            width={72}
            height={72}
            className="rounded-xl"
          />
          <h1 className="text-3xl font-bold text-white tracking-tight">
            logikality
          </h1>
          <p className="text-lg text-white/50 max-w-sm leading-relaxed">
            Decision-ready AI for mortgage operations
          </p>
          <div className="mt-6 h-px w-24 bg-gradient-to-r from-brand-amber to-brand-magenta/60 rounded-full" />
        </div>
      </div>
      {/* Right panel - form */}
      <div className="flex flex-1 items-center justify-center bg-background px-6">
        <div className="w-full max-w-md">
          {/* Mobile logo */}
          <div className="mb-8 flex items-center justify-center gap-2.5 lg:hidden">
            <Image
              src="/logikality_logo.png"
              alt="Logikality"
              width={32}
              height={32}
              className="rounded"
            />
            <span className="text-xl font-semibold tracking-tight">
              logikality
            </span>
          </div>
          {children}
        </div>
      </div>
    </div>
  );
}
