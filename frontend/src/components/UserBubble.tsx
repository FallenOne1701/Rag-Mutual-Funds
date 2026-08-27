export default function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex w-full animate-fade-in-up justify-end">
      <div className="max-w-[85%] rounded-lg rounded-tr-sm bg-primary-container px-4 py-3 text-body-lg text-on-primary-container">
        <p className="whitespace-pre-line break-words">{text}</p>
      </div>
    </div>
  );
}
