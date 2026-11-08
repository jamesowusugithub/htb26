import * as ToggleGroup from '@radix-ui/react-toggle-group';

// Adapted from the Toggle Group listed on 21st.dev, by shadcn (MIT).
export function CameraTabs({items=[],value,onChange,className='',...props}){
  return <ToggleGroup.Root type="single" value={value} onValueChange={next=>{if(next)onChange?.(next);}} aria-label="Camera view" className={`ui-camera-tabs ${className}`} {...props}>
    {items.map(item=><ToggleGroup.Item key={item.id} id={`view-${item.id}`} value={item.id} disabled={item.disabled} className="ui-camera-tab">{item.label}</ToggleGroup.Item>)}
  </ToggleGroup.Root>;
}
