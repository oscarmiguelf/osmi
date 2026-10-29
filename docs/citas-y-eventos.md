# Citas y eventos

[← Volver al manual](README.md)

El módulo se llama **Citas** en Belleza, **Consultas** en Salud y **Eventos** en Música. Muestra las citas de la sucursal donde trabajas en un calendario por mes (en el celular, como agenda), con un color por estado.

## Agendar

Desde el calendario (**Nueva cita**, o el **+** de un día) o desde la ficha del cliente (**Agendar**):

1. **Cliente:** búscalo (desde su ficha ya viene elegido).
2. **Motivo:** por ejemplo "Corte y tinte" o "Boda".
3. **Servicios:** escribe para buscar y elige uno o varios; cada uno muestra su duración y su precio. La **duración** de la cita se propone sola sumando la de los servicios.
4. **Fecha y hora** y **duración**.
5. **Atiende / Responsable (opcional):** una persona no puede tener dos citas a la misma hora.
6. **Datos de la cita:** los campos propios del negocio definidos en Configuración (en Música, por ejemplo: tipo de evento, lugar, dirección, invitados, hora de montaje).
7. **Notas** y, si el cliente ya confirmó, **Ya confirmó**.

## Anticipos y saldo

**Toda cita con servicios genera su venta a crédito al agendarse.** El cliente la paga con abonos: un anticipo al agendar, otros después, o todo de una vez.

Al guardar la cita se abre **Abonar** con el saldo:

- Escribe cuánto paga y con qué. Si paga parte en efectivo y parte con tarjeta, usa **Otra forma de pago**.
- Con efectivo, escribe el **efectivo recibido** para ver el cambio.
- **Registrar abono**, o **Después** si hoy no paga.

En la cita se ve después:

- **Anticipo · saldo $…** junto al estado.
- **Pagado** y **Saldo pendiente**.
- **Registrar pago:** abre el mismo diálogo de abono.
- **Recordar saldo:** abre WhatsApp con un mensaje para el cliente que dice cuánto debe.

Para generar la venta y para abonar hace falta una **caja ocupada**. Si no la tienes, la cita se agenda igual con el aviso "su venta no se generó"; después, con una caja ocupada, pulsa **Generar venta** en la cita.

El saldo de una cita abierta no necesita límite de crédito del cliente.

## La cita

Al abrir una cita:

- **Confirmar**, **Atendida** (o *Realizado* en Música) y **No asistió**.
- **Reagendar:** otra fecha y hora, con el motivo. Una cita reagendada vuelve a quedar por confirmar.
- **Cancelar:** con el motivo. La cita no se borra; queda cancelada en el historial.
- **Editar:** motivo, quién atiende, datos de la cita y notas.
- **Editar servicios.**
- **Seguimiento:** notas que quedan con tu nombre y la hora (no se editan).
- **Historial de cambios.**

### Qué pasa con la venta

- **Cancelar o "No asistió" sin abonos:** la venta se devuelve sola y el cliente deja de deber.
- **Cancelar o "No asistió" con abonos:** aparece un aviso con el enlace **Devolver**, para decidir en la venta si se reembolsa el anticipo.
- **Cambiar los servicios sin abonos:** la venta se rehace con el nuevo total.
- **Cambiar los servicios con abonos:** no se permite desde la cita; el ajuste se hace en la venta.

## Cotización ligada

- **Crear cotización:** si la cita todavía no tiene venta, arma una cotización con sus servicios, vigente hasta la fecha de la cita.
- **Desde una cotización:** [Agendar evento](cotizaciones.md#agendar-un-evento-desde-la-cotización) crea la cita ligada a ella.
- La cita muestra su cotización (folio, total y estado). La venta de la cita respeta los precios cotizados.
- Si cambias los servicios, se hace **una cotización nueva** con ellos: los servicios que se quedan conservan su cantidad y su descuento, y la anterior queda cancelada o en el historial.

## Recordatorios por WhatsApp

**Recordatorios** (en el calendario) muestra las citas de un día (mañana por omisión):

- **WhatsApp** abre el chat del cliente con el mensaje listo; tú lo envías. La cita queda marcada como *Recordatorio enviado*.
- **Confirmó** marca la cita como confirmada cuando el cliente responde.

El texto del mensaje se personaliza en Configuración.

## Solo sus citas

Un administrador puede dar a una persona el permiso **Solo sus citas** (para médicos o terapeutas). Con él solo ve las citas asignadas a ella o que ella agendó: en el calendario, en recordatorios y en el historial de cada cliente. Recepción y administración, sin ese permiso, ven todas.

## Consultas en el giro Salud

Desde una consulta, **Nota de consulta** abre el expediente clínico del paciente para escribir la nota de esa consulta. Ver [Expediente clínico](expediente-clinico.md).
