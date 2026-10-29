# Ventas

[← Volver al manual](README.md)

**Ventas** muestra lo vendido en la sucursal donde trabajas. Tiene cinco pestañas.

## Ventas

La lista de ventas con folio, fecha, cliente, total y estado:

- **Pagada:** cobrada completa.
- **Con saldo:** una parte quedó a crédito.
- **Devuelta:** se devolvió completa.

Filtra por periodo, estado o folio. Desde la ficha de un cliente, **Ver todas sus ventas** abre esta lista con solo sus ventas.

### El detalle de una venta

Al abrir una venta ves el ticket y, según el caso:

- **Imprimir**, **Enviar por WhatsApp** y **Descargar PDF** del ticket.
- **Abonar:** si tiene saldo a crédito.
- **Entregar seleccionados:** si tiene productos apartados.
- **Devolver:** para devolver parte o toda la venta.
- El historial: quién la cobró, abonos, entregas y devoluciones.
- Enlaces a la cotización o la cita de donde salió, si las hay.

## Por entregar

Los productos **apartados** que todavía no se entregan al cliente. Al entregar, abre la venta, marca lo que se lleva y pulsa **Entregar seleccionados**. Una entrega no se puede deshacer.

## Por cobrar

Lo que deben los clientes en esta sucursal, agrupado por cliente con el detalle de cada venta. **Cobrar** abre el abono: el pago se reparte entre sus ventas pendientes, de la más antigua a la más reciente. También se puede abonar desde la [ficha del cliente](clientes.md#abonos) o desde la venta.

Para abonar necesitas una caja ocupada.

## Devoluciones

La lista de devoluciones del periodo, con su folio (por ejemplo `SUC1-R000045`), la venta, el motivo y el monto.

### Hacer una devolución

1. Abre la venta y pulsa **Devolver**.
2. Marca qué productos y cuántos regresan.
3. El sistema calcula lo que corresponde (ya con el descuento de la venta repartido). **Lo que el cliente aún debe se cancela primero**; solo el resto sale de la caja como dinero.
4. Elige cómo se le regresa el dinero y escribe el motivo.

Los productos devueltos regresan a la existencia. Para devolver necesitas una caja ocupada y permiso de devoluciones.

## Reporte

Un resumen del periodo: ventas, devoluciones, lo cobrado por forma de pago y por vendedor. Para análisis más completos ver [Reportes](reportes.md).

## Ventas sin conexión por revisar

Cuando hay ventas hechas sin internet que no cuadraron al enviarse, aparece un aviso arriba de la lista con el enlace. Ver [Vender sin conexión](venta-sin-conexion.md#si-algo-no-cuadra-al-enviarse).
