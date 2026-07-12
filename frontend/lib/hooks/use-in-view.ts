"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Fire-once viewport observer for lazy-loading (decisions/0035). Returns `{ ref, inView }`;
 * `inView` flips true when the element first enters the viewport (expanded by `rootMargin`)
 * and stays true. Used to defer each photo tile's signed-URL fetch until it's near view.
 */
export function useInView<T extends Element>(rootMargin = "300px") {
  const ref = useRef<T>(null);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || inView) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setInView(true);
      },
      { rootMargin },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [inView, rootMargin]);

  return { ref, inView };
}
