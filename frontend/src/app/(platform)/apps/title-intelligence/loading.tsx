export default function TILoading() {
  return (
    <div className="flex items-center gap-3 py-12 justify-center">
      <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      <p className="text-sm text-muted-foreground">Loading...</p>
    </div>
  );
}
