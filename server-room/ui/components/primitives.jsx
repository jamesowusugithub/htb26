import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import * as MenuPrimitive from '@radix-ui/react-dropdown-menu';
import { cva } from 'class-variance-authority';
import { Check } from 'lucide-react';

// Adapted from shadcn/ui's MIT-licensed primitives. Styling belongs to this app.
export const buttonVariants=cva('ui-button',{
  variants:{variant:{default:'ui-button-default',secondary:'ui-button-secondary',outline:'ui-button-outline',ghost:'ui-button-ghost',destructive:'ui-button-destructive'},size:{default:'ui-button-md',sm:'ui-button-sm',icon:'ui-button-icon'}},
  defaultVariants:{variant:'default',size:'default'},
});

export const Button=React.forwardRef(function Button({className='',variant='default',size='default',asChild=false,type='button',...props},ref){
  const Comp=asChild?Slot:'button';
  return <Comp ref={ref} type={asChild?undefined:type} data-slot="button" data-variant={variant} data-size={size} className={buttonVariants({variant,size,className})} {...props}/>;
});

export const TooltipProvider=TooltipPrimitive.Provider;
export const TooltipRoot=TooltipPrimitive.Root;
export const TooltipTrigger=TooltipPrimitive.Trigger;
export const TooltipContent=React.forwardRef(function TooltipContent({className='',sideOffset=7,children,...props},ref){
  return <TooltipPrimitive.Portal><TooltipPrimitive.Content ref={ref} sideOffset={sideOffset} className={`ui-tooltip ${className}`} data-ui-overlay="" {...props}>{children}<TooltipPrimitive.Arrow className="ui-tooltip-arrow"/></TooltipPrimitive.Content></TooltipPrimitive.Portal>;
});
export function Tooltip({content,children,side='top',delayDuration=350,...props}){
  return <TooltipPrimitive.Provider delayDuration={delayDuration}><TooltipPrimitive.Root {...props}><TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger><TooltipContent side={side}>{content}</TooltipContent></TooltipPrimitive.Root></TooltipPrimitive.Provider>;
}

export const DropdownMenu=MenuPrimitive.Root;
export const DropdownMenuTrigger=MenuPrimitive.Trigger;
export const DropdownMenuGroup=MenuPrimitive.Group;
export const DropdownMenuRadioGroup=MenuPrimitive.RadioGroup;
export const DropdownMenuContent=React.forwardRef(function DropdownMenuContent({className='',sideOffset=7,align='end',...props},ref){
  return <MenuPrimitive.Portal><MenuPrimitive.Content ref={ref} sideOffset={sideOffset} align={align} collisionPadding={12} className={`ui-menu ${className}`} data-ui-overlay="" {...props}/></MenuPrimitive.Portal>;
});
export const DropdownMenuItem=React.forwardRef(function DropdownMenuItem({className='',variant='default',...props},ref){
  return <MenuPrimitive.Item ref={ref} data-variant={variant} className={`ui-menu-item ${className}`} {...props}/>;
});
export const DropdownMenuRadioItem=React.forwardRef(function DropdownMenuRadioItem({className='',children,...props},ref){
  return <MenuPrimitive.RadioItem ref={ref} className={`ui-menu-item ui-menu-radio ${className}`} {...props}><span className="ui-menu-indicator"><MenuPrimitive.ItemIndicator><Check size={14} aria-hidden="true"/></MenuPrimitive.ItemIndicator></span>{children}</MenuPrimitive.RadioItem>;
});
export const DropdownMenuSeparator=React.forwardRef(function DropdownMenuSeparator({className='',...props},ref){return <MenuPrimitive.Separator ref={ref} className={`ui-menu-separator ${className}`} {...props}/>;});
export const DropdownMenuLabel=React.forwardRef(function DropdownMenuLabel({className='',...props},ref){return <MenuPrimitive.Label ref={ref} className={`ui-menu-label ${className}`} {...props}/>;});
