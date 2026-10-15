import * as Alert from "@radix-ui/react-alert-dialog";
import type { ComponentProps } from "react";
export const AlertDialog = Alert.Root;
export const AlertDialogTitle = Alert.Title;
export const AlertDialogDescription = Alert.Description;
export const AlertDialogAction = Alert.Action;
export const AlertDialogCancel = Alert.Cancel;
export function AlertDialogContent({
  children,
  ...props
}: ComponentProps<typeof Alert.Content>) {
  return (
    <Alert.Portal>
      <Alert.Overlay className="dialog-overlay" />
      <Alert.Content className="dialog-content" {...props}>
        {children}
      </Alert.Content>
    </Alert.Portal>
  );
}
