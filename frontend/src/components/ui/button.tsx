// Adapted from shadcn/ui (MIT); locally owned tokens and variants.
import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";
const buttonVariants = cva("ui-button", {
  variants: {
    variant: {
      default: "ui-primary",
      outline: "ui-outline",
      ghost: "ui-ghost",
      destructive: "ui-destructive",
    },
    size: { default: "ui-default", sm: "ui-small", icon: "ui-icon" },
  },
  defaultVariants: { variant: "default", size: "default" },
});
export function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      data-slot="button"
      data-variant={variant || "default"}
      data-size={size || "default"}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}
