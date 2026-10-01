import Studio from "@/components/studio";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <Studio applicationId={id} />;
}
