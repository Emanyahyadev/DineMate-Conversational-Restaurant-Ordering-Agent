import Image from "next/image";

/**
 * The DineMate mascot, cropped out of the full logo lockup so it reads at avatar
 * sizes. The full lockup (wordmark included) lives at /dinemate-logo.png.
 */
export default function BrandMark({
  size,
  priority = false,
}: {
  size: number;
  priority?: boolean;
}) {
  return (
    <Image
      src="/dinemate-mark.png"
      alt=""
      aria-hidden
      width={size}
      height={size}
      priority={priority}
      className="shrink-0 select-none"
    />
  );
}
