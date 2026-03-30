import Image from "next/image";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen">
      {/* Left panel - branding */}
      <div className="hidden lg:flex lg:w-1/2 bg-background items-center justify-center relative overflow-hidden border-r border-border">
        {/* Decorative circles */}
        <div className="absolute top-20 left-20 h-64 w-64 rounded-full bg-brand-amber/8 blur-3xl" />
        <div className="absolute bottom-20 right-20 h-48 w-48 rounded-full bg-brand-magenta/8 blur-3xl" />
        <div className="relative z-10 flex flex-col items-center gap-6 px-12 text-center">
          <Image
            src="/Logo_withTagline.svg"
            alt="Logikality"
            width={240}
            height={64}
            priority
          />
          <p className="text-lg text-muted-foreground max-w-sm leading-relaxed">
            Decision-ready AI for mortgage operations
          </p>
          <div className="mt-6 h-px w-24 bg-gradient-to-r from-brand-amber to-brand-magenta/60 rounded-full" />
        </div>
      </div>
      {/* Right panel - form */}
      <div className="flex flex-1 items-center justify-center bg-background px-6">
        <div className="w-full max-w-md">
          {/* Mobile logo */}
          <div className="mb-8 flex items-center justify-center lg:hidden">
            <Image
              src="/Logo_withTagline.svg"
              alt="Logikality"
              width={200}
              height={56}
              priority
            />
          </div>
          {children}
        </div>
      </div>
    </div>
  );
}
