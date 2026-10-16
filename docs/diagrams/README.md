# Diagramas de arquitectura

Fuente editable en Mermaid (`.mmd`, una por arquitectura), exportada tambien
como PNG (`centralized.png`, `hierarchical.png`, `decentralized.png`) para
verlas sin un visor Mermaid. Este archivo ademas incrusta las mismas tres
fuentes en bloques ` ```mermaid ` para que se rendericen directamente en
GitHub/GitLab.

## Centralizada

```mermaid
flowchart TD
    User((Usuario)) --> Supervisor[Central Supervisor]

    Supervisor -->|as_tool| FAQAgent[FAQ Agent]
    Supervisor -->|as_tool| WeatherAgent[Weather Agent]
    Supervisor -->|as_tool| SchedulingAgent[Scheduling Agent]

    FAQAgent -->|search_faq| FaqService[(FAQ Service /\nknowledge base)]
    WeatherAgent -->|check_jump_day| WeatherService[Weather Service]
    SchedulingAgent -->|check_appointment_availability\ncreate_appointment| CalendarService[Calendar Service\n in-memory]

    WeatherService --> DatePolicy[date_policy]
    WeatherService --> OpenMeteo[(Open-Meteo API)]
    WeatherService --> WeatherPolicy[weather_policy\n deterministico]

    classDef shared fill:#eef,stroke:#448;
    class FaqService,WeatherService,CalendarService,OpenMeteo,DatePolicy,WeatherPolicy shared;
```

## Jerárquica

```mermaid
flowchart TD
    User((Usuario)) --> Root[Root Manager]

    Root -->|as_tool| Knowledge[Knowledge Manager]
    Root -->|as_tool| Booking[Booking Manager]

    Knowledge -->|as_tool| FAQAgent[FAQ Agent]
    Booking -->|as_tool| WeatherAgent[Weather Agent]
    Booking -->|as_tool| SchedulingAgent[Scheduling Agent]

    FAQAgent -->|search_faq| FaqService[(FAQ Service /\nknowledge base)]
    WeatherAgent -->|check_jump_day| WeatherService[Weather Service]
    SchedulingAgent -->|check_appointment_availability\ncreate_appointment| CalendarService[Calendar Service\n in-memory]

    WeatherService --> DatePolicy[date_policy]
    WeatherService --> OpenMeteo[(Open-Meteo API)]
    WeatherService --> WeatherPolicy[weather_policy\n deterministico]

    classDef shared fill:#eef,stroke:#448;
    class FaqService,WeatherService,CalendarService,OpenMeteo,DatePolicy,WeatherPolicy shared;
```

## Descentralizada

```mermaid
flowchart TD
    User((Usuario)) --> FAQAgent[FAQ Agent]

    FAQAgent -->|handoff| WeatherAgent[Weather Agent]
    WeatherAgent -->|handoff| SchedulingAgent[Scheduling Agent]
    WeatherAgent -->|handoff| FAQAgent
    SchedulingAgent -->|handoff| FAQAgent

    FAQAgent -->|search_faq| FaqService[(FAQ Service /\nknowledge base)]
    WeatherAgent -->|check_jump_day| WeatherService[Weather Service]
    SchedulingAgent -->|check_appointment_availability\ncreate_appointment| CalendarService[Calendar Service\n in-memory]

    WeatherService --> DatePolicy[date_policy]
    WeatherService --> OpenMeteo[(Open-Meteo API)]
    WeatherService --> WeatherPolicy[weather_policy\n deterministico]

    classDef shared fill:#eef,stroke:#448;
    class FaqService,WeatherService,CalendarService,OpenMeteo,DatePolicy,WeatherPolicy shared;
```

Nota de anti-bypass (aplica a las tres, especialmente relevante en la
descentralizada por sus ciclos de handoffs): `create_appointment` exige que
`context.jump_assessment` exista y corresponda a la fecha solicitada,
independientemente de la ruta de `as_tool()`/handoffs que se haya seguido
para llegar ahi.
